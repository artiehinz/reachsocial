from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from reachsocial.catalog import Catalog, InputField, ProviderConfig, ServiceDefinition
from reachsocial.db import Base, make_engine
from reachsocial.models import Client
from reachsocial.security import generate_api_key, hash_api_key


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session


@pytest.fixture
def client(session):
    api_key = generate_api_key()
    row = Client(name="InstaGet", api_key_hash=hash_api_key(api_key), billing_mode="internal")
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def catalog():
    return Catalog(
        services=[
            ServiceDefinition(
                id="instagram.profile",
                title="Instagram Profile",
                platform="Instagram",
                description="Test service",
                input_fields=[InputField(name="url", description="Profile URL", format="url")],
                provider=ProviderConfig(name="mock"),
                enabled=True,
                public=True,
            ),
            ServiceDefinition(
                id="instagram.post",
                title="Instagram Post",
                platform="Instagram",
                description="Disabled test service",
                input_fields=[InputField(name="url", description="Post URL", format="url")],
                provider=ProviderConfig(name="mock"),
                enabled=False,
                public=False,
            ),
        ]
    )
