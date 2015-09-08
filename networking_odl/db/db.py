import time

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import orm
from sqlalchemy.orm import exc

import neutron.db.api as db
from networking_odl.db.models import OpendaylightJournal


def _check_for_pending_or_processing_ops(session, object_uuid):
    return session.query(OpendaylightJournal).filter(
        or_(OpendaylightJournal.state == 'pending',
            OpendaylightJournal.state == 'processing'),
        object_uuid == object_uuid).all()

def get_untried_db_row_with_lock(session=None):
    if session is None:
        session = db.get_session()

    return session.query(OpendaylightJournal).filter_by(
           state='pending', retry_count=0).with_for_update().first()

def get_pending_db_row_with_lock(session=None):
    if session is None:
        session = db.get_session()

    return session.query(OpendaylightJournal).filter_by(
           state='pending').with_for_update().first()

def update_pending_db_row_processing(row):
    row.update(state='processing')

def update_pending_db_row_retry(row):
    row.update({'retry_count': row.retry_count + 1,
                'state': 'pending'})

def update_processing_db_row_passed(row):
    row.update(state='completed')

def update_pending_db_row_failed(row):
    row.update({'retry_count': row.retry_count + 1,
                'state': 'failed'})

def delete_row(session, row=None, row_id=None):
    if session is None:
        session = db.get_session()
    if row_id:
        row = session.query(OpendaylightJournal).filter_by(id=row_id).one()
    if row:
        session.delete(row)
        session.flush()

def create_pending_row(session, object_type, object_uuid,
                       operation, data):
    if session is None:
        session = db.get_session()
    row = OpendaylightJournal(object_type=object_type, object_uuid=object_uuid,
                              operation=operation, data=data,
                              created_at=func.now(), state='pending')
    session.add(row)
    session.flush()

def validate_operation(session, object_type, object_uuid, operation,
                       data):
    """Validate an operation based on dependencies.

    Validate an operation depending on whether it's dependencies
    are still in 'pending' or 'processing' state. e.g. 
    """
    if session is None:
        session = db.get_session()

    if object_type in ('port', 'subnet'):
        network_id = data['network_id']
        # Check for pending or processing network operations
        ops = _check_for_pending_or_processing_ops(session, network_id)
        # Check for pending subnet operations if it's a port
        if object_type is 'port':
            for fixed_ip in data['fixed_ips']:
                ops += _check_for_pending_or_processing_ops(
                    session, fixed_ip['subnet_id'])
        if ops:
            return False

    return True
