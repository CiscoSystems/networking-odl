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
from networking_odl.db import db

from neutron.common import constants as n_const
from neutron.extensions import portbindings
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api as api

LOG = logging.getLogger(__name__)

# TODO(rcurran): Make configurable. (Config under /neutron today.)
ODL_SYNC_THREAD_TIMEOUT = 10


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
        self._odl_sync_timeout = ODL_SYNC_THREAD_TIMEOUT
        self._odl_sync_lock = threading.Lock()
        self._odl_sync_thread()

    def _odl_sync_thread(self):
        with self._odl_sync_lock:
            self.odl_synchronize()

        self.timer = threading.Timer(self._odl_sync_timeout,
                                     self._odl_sync_thread)
        self.timer.start()

    # TODO(rcurran): Keep this method here or new class/module?
    def odl_synchronize(self):
        pass

    def stop_odl_sync_thread(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def create_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'create_network', context.current)

    def create_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'create_subnet', context.current)

    def create_port_precommit(self, context):
        db.create_pending_row(None, 'port', context.current['id'],
                              'create_port', context.current)

    def update_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'update_network', context.current)

    def update_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'update_subnet', context.current)

    def update_port_precommit(self, context):
        db.create_pending_row(None, 'port', context.current['id'],
                              'update_port', context.current)

    def delete_network_precommit(self, context):
        db.create_pending_row(None, 'network', context.current['id'],
                              'delete_network', context.current)

    def delete_subnet_precommit(self, context):
        db.create_pending_row(None, 'subnet', context.current['id'],
                              'delete_subnet', context.current)

    def delete_port_precommit(self, context):
        db.create_pending_row(None, 'port', context.current['id'],
                              'delete_port', context.current)

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
