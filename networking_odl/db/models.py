import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base

from neutron.db import model_base
from neutron.db.models_v2 import HasId

class OpendaylightJournal(model_base.BASEV2, HasId):
    __tablename__ = 'opendaylightjournal'

    object_type = sa.Column(sa.Enum('network','port','subnet'), nullable=False)
    object_uuid = sa.Column(sa.String(36), nullable=False)
    operation = sa.Column(sa.Enum('create', 'update', 'delete'),
                          nullable=False)
    data = sa.Column(sa.PickleType, nullable=True)
    state = sa.Column(sa.Enum('pending', 'failed', 'processing', 'completed'))
    retry_count = sa.Column(sa.Integer, default=0)
    created_at = sa.Column(sa.TIMESTAMP, nullable=False)
    last_retried = sa.Column(sa.TIMESTAMP, nullable=True)
