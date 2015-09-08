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

import threading

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from neutron.db import model_base
from networking_odl.common import constants as odl_const
from networking_odl.common import config as odl_conf
from networking_odl.db import db
from networking_odl.common import utils as odl_utils

from neutron.common import constants as n_const
from neutron.extensions import portbindings
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api as api

from networking_odl.common.client import OpenDaylightRestClient

LOG = logging.getLogger(__name__)

# TODO(rcurran): Make configurable. (Config under /neutron today.)
ODL_SYNC_THREAD_TIMEOUT = 10


class OpendaylightJournalThread(object):
    """Thread worker for the Opendaylight Journal Database."""
    def __init__(self):
        self.client = OpenDaylightRestClient(
            cfg.CONF.ml2_odl.url,
            cfg.CONF.ml2_odl.username,
            cfg.CONF.ml2_odl.password,
            cfg.CONF.ml2_odl.timeout
        )

    @staticmethod
    def filter_create_network_attributes(network):
        """Filter out network attributes not required for a create."""
        odl_utils.try_del(network, ['status', 'subnets', 'vlan_transparent',
                          'mtu'])

    @staticmethod
    def filter_create_subnet_attributes(subnet):
        """Filter out subnet attributes not required for a create."""
        pass

    @classmethod
    def filter_create_port_attributes(port):
        """Filter out port attributes not required for a create."""
        #cls.add_security_groups(port, context)
        # TODO(kmestery): Converting to uppercase due to ODL bug
        # https://bugs.opendaylight.org/show_bug.cgi?id=477
        port['mac_address'] = port['mac_address'].upper()
        odl_utils.try_del(port, ['status'])

    @staticmethod
    def filter_update_network_attributes(network):
        """Filter out network attributes for an update operation."""
        odl_utils.try_del(network, ['id', 'status', 'subnets', 'tenant_id',
                          'vlan_transparent', 'mtu'])

    @staticmethod
    def filter_update_subnet_attributes(subnet):
        """Filter out subnet attributes for an update operation."""
        odl_utils.try_del(subnet, ['id', 'network_id', 'ip_version', 'cidr',
                          'allocation_pools', 'tenant_id'])

    @classmethod
    def filter_update_port_attributes(port):
        """Filter out port attributes for an update operation."""
        #cls.add_security_groups(port, context)
        odl_utils.try_del(port, ['network_id', 'id', 'status', 'mac_address',
                          'tenant_id', 'fixed_ips'])

    @staticmethod
    def add_security_groups(port, context):
        """Populate the 'security_groups' field with entire records."""
        dbcontext = context._plugin_context
        groups = [context._plugin.get_security_group(dbcontext, sg)
                  for sg in port['security_groups']]
        port['security_groups'] = groups

    def sync_pending_row(self):
        LOG.debug("Thread walking database")
        row = db.get_pending_db_row_with_lock(None)
        if not row:
            return
        LOG.debug("Syncing pending row")
        # Add code to sync this to ODL
        if row.operation == 'delete':
            method = 'delete'
            data = None
            urlpath = row.object_type + 's/' + row.object_uuid
        if row.operation == 'create':
            method = 'post'
            attr_filter = self.create_object_map[row.object_type]
            data = row.data
            urlpath = row.object_type + 's'
        elif row.operation == 'update':
            method = 'put'
            attr_filter = self.update_object_map[row.object_type]
            data = row.data
            urlpath = row.object_type + 's/' + row.object_uuid

        attr_filter(data)
        try:
            self.client.sendjson(method, urlpath, {row.object_type: data})
            db.update_pending_row_processing(row)
        except Exception:
            LOG.error("Error syncing pending row")
            db.update_pending_db_row_retry(row)

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
        self.journal = OpendaylightJournalThread()
        self._odl_sync_timeout = ODL_SYNC_THREAD_TIMEOUT
        self._odl_sync_lock = threading.Lock()
        self._odl_sync_thread()

    def _odl_sync_thread(self):
        with self._odl_sync_lock:
            self.journal.sync_pending_row()

        self.timer = threading.Timer(self._odl_sync_timeout,
                                     self._odl_sync_thread)
        self.timer.start()

    def stop_odl_sync_thread(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def create_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'create', context.current)

    def create_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'create', context.current)

    def create_port_precommit(self, context):
        db.create_pending_row(None, 'port', context.current['id'],
                              'create', context.current)

    def update_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'update', context.current)

    def update_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'update', context.current)

    def update_port_precommit(self, context):
        db.create_pending_row(None, 'port', context.current['id'],
                              'update', context.current)

    def delete_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'delete', context.current)

    def delete_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'delete', context.current)

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

OpendaylightJournalThread.create_object_map = {
    odl_const.ODL_NETWORK:
        OpendaylightJournalThread.filter_create_network_attributes,
    odl_const.ODL_SUBNET:
        OpendaylightJournalThread.filter_create_subnet_attributes,
    odl_const.ODL_PORT:
        OpendaylightJournalThread.filter_create_port_attributes}

OpendaylightJournalThread.update_object_map = {
    odl_const.ODL_NETWORK:
        OpendaylightJournalThread.filter_update_network_attributes,
    odl_const.ODL_SUBNET:
        OpendaylightJournalThread.filter_update_subnet_attributes,
    odl_const.ODL_PORT:
        OpendaylightJournalThread.filter_update_port_attributes}
