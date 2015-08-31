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

from networking_odl.db import db

from neutron.tests import base


class OpendaylightDBTestCase(base.BaseTestCase):

    def setUp(self):
        self.network = {'name': 'net1', 'uuid':'1234'}
        self.subnet = {'name': 'sub1', 'uuid': '5678', 'network_id': '1234'}
        self.port = {'uuid': '9999', 'network_id': '1234',
                     'fixed_ips': [{'subnet_id': '5678']}}
        super(OpendaylightDBTestCase, self).setUp()

    def _test_create_pending_row(object_type, operation):
        obj = getattr(self, object_type)
        uuid = getattr(obj, uuid)
        db.create_pending_row(None, object_type, uuid, operation, obj)
        row = db.get_untried_db_row_with_lock()
        self.assertEqual(row.object_uuid, uuid)
        self.assertEqual(row.operation, operation)
        self.assertEqual(row.object_type, object_type)
        self.assertEqual(row.state, 'pending')
        db.delete_row(None, row)

    def test_create_pending_network_row(self):
        for operation in ('create', 'update', 'delete'):
            self._test_create_pending_row('network', operation)

    def test_create_pending_subnet_row(self):
        for operation in ('create', 'update', 'delete'):
            self._test_create_pending_row('subnet', operation)

    def test_create_pending_port_row(self):
        for operation in ('create', 'update', 'delete'):
            self._test_create_pending_row('port', operation)
