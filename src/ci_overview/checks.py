"""Fetch and parse information about declared checks."""

from collections.abc import Iterable
from dataclass import dataclass
import shlex

from gql import gql
from graphql.language.ast import DocumentNode

from ci_overview.api_client import Client

DEFAULTENV: str = 'DEFAULTS.env'
TIMEFORMAT: str = '%Y-%m-%dT%H:%M:%SZ'
CHECK_DEFS_GRAPHQL: DocumentNode = gql('''\
query files($repoOwner: String!, $repoName: String!, $object: String!) {
  repository(name: $repoName, owner: $repoOwner) {
    object(expression: $object) {
      # Directories are at most 3 levels deep. We can't put the `...
      # on Tree` stuff in a fragment as that would recurse forever.
      # We need fileContents at each level to get all DEFAULTS.envs.
      ... on Tree {
        entries {
          path
          object {
            ...fileContents
            ... on Tree {
              entries {
                path
                object {
                  ...fileContents
                  ... on Tree {
                    entries {
                      path
                      object {
                        ...fileContents
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

fragment fileContents on Blob {
  text
  isTruncated
}
''')


@dataclass
class Check:
    """A generic check, as parsed from a .env file."""
    short_name: str
    name: str
    repository: str
    branch: str


def parse_env_file(contents: str) -> dict[str, str]:
    result = {}
    for token in shlex.split(contents, comments=False):
        var, is_assignment, value = token.partition('=')
        if is_assignment:
            result[var] = value
    return result


def process_gql_directory(directory: dict[str, dict], common_path: str) \
        -> Iterable[tuple[tuple[str], str]]:
    common_path = common_path.strip('/') + '/'
    for entry in directory['object']['entries']:
        if 'text' in entry['object']:
            # This is a file. Get its contents.
            assert not entry['object']['isTruncated'], \
                f'got truncated object {entry["path"]}'
            yield (tuple(entry['path'].removeprefix(common_path).split('/')),
                   parse_env_file(entry['object']['text']))
        else:
            # This is a directory. Recurse.
            yield from process_gql_directory(entry)


def get_all_checks(client: Client,
                   defs_repo: str = 'alisw/ali-bot',
                   defs_branch: str = 'master',
                   defs_dir: str = 'ci/repo-config') -> list[dict[str, str]]:
    '''Fetch and parse .env files, returning checks' variable definitions.

    Variable definitions are returned with defaults applied.
    '''
    owner, have_sep, repo = defs_repo.partition('/')
    if not have_sep:
        raise ValueError(f'repo not in ORG/REPO syntax: {defs_repo!r}')
    env_files = list(process_gql_directory(client.execute(CHECK_DEFS_GRAPHQL, {
        'repoOwner': owner, 'repoName': repo,
        'object': f'{defs_branch}:{defs_dir.strip("/")}',
    })['data']['repository']))
    defaults = {path[:-1]: variables for path, variables in env_files
                if path[-1] == 'DEFAULTS.env'}
    checks = []
    for path, variables in env_files:
        if path[-1] == 'DEFAULTS.env':
            continue
        role, container, filename = path
        # Give this a name that couldn't be an env var name.
        check = {}
        check.update(defaults.get((), {}))
        check.update(defaults.get((role,), {}))
        check.update(defaults.get((role, container), {}))
        check.update(variables)
        checks.append(Check(
            short_name=filename.removesuffix('.env'),  # TODO: needed?
            name=check['CHECK_NAME'],
            repository=check['PR_REPO'],
            branch=check['PR_BRANCH'],
        ))
    return checks
