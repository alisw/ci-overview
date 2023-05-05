"""Set up GitHub GraphQL API clients."""

from __future__ import annotations
import os
import sys
from typing import NoReturn

from gql import Client
from gql.transport.requests import RequestsHTTPTransport


def make_client() -> Client | NoReturn:
    try:
        github_token = os.environ['GITHUB_TOKEN']
    except KeyError:
        print('Please define the GITHUB_TOKEN environment variable!',
              file=sys.stderr)
        sys.exit(1)
    return Client(
        transport=RequestsHTTPTransport(
            url='https://api.github.com/graphql',
            headers={'Authorization': f'bearer {github_token}'},
        ),
        # fetch_schema_from_transport=True,  # is this slow?
    )
