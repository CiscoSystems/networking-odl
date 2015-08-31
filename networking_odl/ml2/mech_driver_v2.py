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
