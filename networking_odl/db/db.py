import time

from sqlalchemy import asc
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
        OpendaylightJournal.object_uuid == object_uuid).all()

def get_untried_db_row_with_lock(session=None):
    if session is None:
        session = db.get_session()

    return session.query(OpendaylightJournal).filter_by(
           state='pending', retry_count=0).with_for_update().first()


def get_all_db_rows(session=None):
    if session is None:
        session = db.get_session()

    return session.query(OpendaylightJournal).all()


def get_all_db_rows_by_state(session, state):
    if session is None:
        session = db.get_session()

    return session.query(OpendaylightJournal).filter_by(state=state).all()


def get_oldest_pending_db_row_with_lock(session=None):
    if session is None:
        session = db.get_session()

    return session.query(OpendaylightJournal).filter_by(
           state='pending').order_by(
           asc(OpendaylightJournal.last_retried)).with_for_update().first()

def update_pending_db_row_processing(session, row):
    if session is None:
        session = db.get_session()

    row.state='processing'
    session.merge(row)
    session.flush()

def update_pending_db_row_retry(session, row):
    if session is None:
        session = db.get_session()
    # asomya TODO: make this configurable
    if row.retry_count >= 5:
        row.state = 'failed'
    else:
        row.retry_count = row.retry_count + 1
        row.state = 'pending'
    session.merge(row)
    session.flush()

def update_processing_db_row_passed(session, row):
    if session is None:
        session = db.get_session()
    row.state = 'completed'
    session.merge(row)
    session.flush()

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

    if operation in ('create', 'update'):
        if object_type in ('port', 'subnet'):
            network_id = data['network_id']
            # Check for pending or processing network operations
            ops = _check_for_pending_or_processing_ops(session, network_id)
            # Check for pending subnet operations if it's a port
            if object_type == 'port':
                for fixed_ip in data['fixed_ips']:
                    ops += _check_for_pending_or_processing_ops(
                        session, fixed_ip['subnet_id'])
            if ops:
                return False
    elif operation == 'delete':
        if object_type == 'network':
            # TODO:Check for pending subnet operations
            pass
        elif object_type == 'subnet':
            # TODO:Check for pending port operations
            pass
    return True
