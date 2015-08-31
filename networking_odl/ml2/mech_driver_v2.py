# Copyright (c) 2013-2014 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import time
import threading

from copy import deepcopy

from oslo_config import cfg
from oslo_log import log as logging
from requests import exceptions

from networking_odl.common import config as odl_conf
from networking_odl.common import constants as odl_const
from networking_odl.db import db
from networking_odl.ml2 import filters
from networking_odl.openstack.common._i18n import _LE
from networking_odl.openstack.common._i18n import _LI

from neutron.common import constants as n_const
from neutron.db import model_base
from neutron.extensions import portbindings
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api as api

from networking_odl.common.client import OpenDaylightRestClient

LOG = logging.getLogger(__name__)

# TODO(rcurran): Make configurable. (Config under /neutron today.)
ODL_SYNC_THREAD_TIMEOUT = 10


class OpendaylightJournalThread(object):
    """Thread worker for the Opendaylight Journal Database."""
    FILTER_MAP = {
        odl_const.ODL_NETWORK: filters.NetworkFilter,
        odl_const.ODL_SUBNET: filters.SubnetFilter,
        odl_const.ODL_PORT: filters.PortFilter,
        odl_const.ODL_SGS: filters.SecurityGroupFilter,
        odl_const.ODL_SG_RULES: filters.SecurityGroupRuleFilter,
    }

    def __init__(self):
        self.client = OpenDaylightRestClient(
            cfg.CONF.ml2_odl.url,
            cfg.CONF.ml2_odl.username,
            cfg.CONF.ml2_odl.password,
            cfg.CONF.ml2_odl.timeout
        )

    def sync_pending_row(self):
        # Block until all pending rows are processed
        while True:
            LOG.debug("Thread walking database")
            row = db.get_oldest_pending_db_row_with_lock(None)
            if not row:
                break
            valid = db.validate_operation(None, row.object_type,
                                          row.object_uuid,
                                          row.operation, row.data)
            if not valid:
                LOG.info(_LI("%(operation)s %(type)s %(uuid)s is not a "
                             "valid operation yet, skipping for now"),
                         {'operation': row.operation,
                          'type': row.object_type,
                          'uuid': row.object_uuid})
                continue

            LOG.info(_LI("Syncing %(operation)s %(type)s %(uuid)s"),
                     {'operation': row.operation, 'type': row.object_type,
                      'uuid': row.object_uuid})
            filter_cls = self.FILTER_MAP[row.object_type]
            # Add code to sync this to ODL
            if row.operation == 'delete':
                method = 'delete'
                data = None
                urlpath = row.object_type + 's/' + row.object_uuid
                to_send = None
            if row.operation == 'create':
                method = 'post'
                attr_filter = filter_cls.filter_create_attributes
                data = deepcopy(row.data)
                urlpath = row.object_type + 's'
                attr_filter(data)
                to_send = {row.object_type: data}
            elif row.operation == 'update':
                method = 'put'
                attr_filter = filter_cls.filter_update_attributes
                data = deepcopy(row.data)
                urlpath = row.object_type + 's/' + row.object_uuid
                attr_filter(data)
                to_send = {row.object_type: data}
            try:
                self.client.sendjson(method, urlpath, to_send)
                # NOTE: This will be marked 'processing' once we have
                # the asynchronous communication worked out with the ODL folks.
                db.update_processing_db_row_passed(None, row)
            except exceptions.ConnectionError as e:
                # Don't raise the retry count, just log an error
                LOG.error(_LE("Cannot connect to Opendaylight"))
                # Sleep to avoid  hammering the cpu
                time.sleep(2)
            except Exception as e:
                LOG.error(_LE("Error syncing %(type)s %(operation)s,"
                              " id %(uuid)s Error: %(error)s"),
                          {'type': row.object_type,
                           'uuid': row.object_uuid,
                           'operation': row.operation,
                           'error': e.message})
                db.update_pending_db_row_retry(None, row)


def call_thread_on_end(func):
    def new_func(obj, context):
        func(obj, context)
        obj.start_odl_sync_thread()
    return new_func


class OpenDaylightMechanismDriver(api.MechanismDriver):
    """OpenDaylight Python Driver for Neutron.

    This code is the backend implementation for the OpenDaylight ML2
    MechanismDriver for OpenStack Neutron.
    """

    def initialize(self):
        # asomya: Temp code to create the journal table till a proper
        # migration is added
        model_base.BASEV2.metadata.create_all(db.db.get_engine())
        LOG.debug("Initializing OpenDaylight ML2 driver")
        cfg.CONF.register_opts(odl_conf.odl_opts, "ml2_odl")
        self.vif_details = {portbindings.CAP_PORT_FILTER: True}
        self.journal = OpendaylightJournalThread()
        self._odl_sync_timeout = ODL_SYNC_THREAD_TIMEOUT
        self.start_odl_sync_thread()

    def start_odl_sync_thread(self):
        # Don't start a second thread if there is one alive already
        if (hasattr(self, '_odl_sync_thread') and
           self._odl_sync_thread.isAlive()):
            return

        self._odl_sync_thread = threading.Thread(
            name='sync',
            target=self.journal.sync_pending_row)
        self._odl_sync_thread.start()

        if hasattr(self, 'timer'):
            LOG.debug("Resetting thread timer")
            self.timer.cancel()
            self.timer = None
        self.timer = threading.Timer(self._odl_sync_timeout,
                                     self.start_odl_sync_thread)
        self.timer.start()

    def stop_odl_sync_thread(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    @call_thread_on_end
    def create_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'create', context.current)

    @call_thread_on_end
    def create_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'create', context.current)

    @call_thread_on_end
    def create_port_precommit(self, context):
        dbcontext = context._plugin_context
        groups = [context._plugin.get_security_group(dbcontext, sg)
                  for sg in context.current['security_groups']]
        context.current['security_groups'] = groups
        tenant_id = context._network_context._network['tenant_id']
        context.current['tenant_id'] = tenant_id
        db.create_pending_row(None, 'port', context.current['id'],
                              'create', context.current)

    @call_thread_on_end
    def update_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'update', context.current)

    @call_thread_on_end
    def update_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'update', context.current)

    @call_thread_on_end
    def update_port_precommit(self, context):
        port = context._plugin.get_port(context._plugin_context,
                                        context.current['id'])
        dbcontext = context._plugin_context
        groups = [context._plugin.get_security_group(dbcontext, sg)
                  for sg in port['security_groups']]
        context.current['security_groups'] = groups
        # Add the network_id in for validation
        context.current['network_id'] = port['network_id']
        port['tenant_id'] = context._network_context._network['tenant_id']
        db.create_pending_row(None, 'port', context.current['id'],
                              'update', context.current)

    @call_thread_on_end
    def delete_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'delete', context.current)

    @call_thread_on_end
    def delete_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'delete', context.current)

    @call_thread_on_end
    def delete_port_precommit(self, context):
        db.create_pending_row(None, 'port', context.current['id'],
                              'delete', context.current)

    def bind_port(self, port_context):
        """Set binding for all valid segments

        """

        valid_segment = None
        for segment in port_context.segments_to_bind:
            if self._check_segment(segment):
                valid_segment = segment
                break

        if valid_segment:
            vif_type = self._get_vif_type(port_context)
            LOG.debug("Bind port %(port)s on network %(network)s with valid "
                      "segment %(segment)s and VIF type %(vif_type)r.",
                      {'port': port_context.current['id'],
                       'network': port_context.network.current['id'],
                       'segment': valid_segment, 'vif_type': vif_type})

            port_context.set_binding(
                segment[api.ID], vif_type,
                self.vif_details,
                status=n_const.PORT_STATUS_ACTIVE)

    def _check_segment(self, segment):
        """Verify a segment is valid for the OpenDaylight MechanismDriver.

        Verify the requested segment is supported by ODL and return True or
        False to indicate this to callers.
        """

        network_type = segment[api.NETWORK_TYPE]
        return network_type in [constants.TYPE_LOCAL, constants.TYPE_GRE,
                                constants.TYPE_VXLAN, constants.TYPE_VLAN]

    def _get_vif_type(self, port_context):
        """Get VIF type string for given PortContext

        Dummy implementation: it always returns following constant.
        neutron.extensions.portbindings.VIF_TYPE_OVS
        """

        return portbindings.VIF_TYPE_OVS
