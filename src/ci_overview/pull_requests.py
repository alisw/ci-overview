"""Fetch information about pull requests and their check states."""

from collections import defaultdict
from datetime import datetime
from typing import Literal, TypedDict

from gql import gql
from graphql.language.ast import DocumentNode

State = Literal['EXPECTED'] | Literal['ERROR'] | Literal['FAILURE'] | \
    Literal['PENDING'] | Literal['SUCCESS']
VALID_STATUSES: tuple[State, ...] = \
    'EXPECTED', 'PENDING', 'FAILURE', 'ERROR', 'SUCCESS'

NOW: datetime = datetime.utcnow()
GET_PR_STATUSES_GRAPHQL: DocumentNode = gql('''\
query statuses($repoOwner: String!, $repoName: String!, $baseBranch: String!) {
  repository(owner: $repoOwner, name: $repoName) {
    pullRequests(last: 50, baseRefName: $baseBranch, states: OPEN) {
      nodes {
        number
        title
        isDraft
        commits(last: 1) {
          nodes {
            commit {
              oid
              status {
                contexts {
                  context
                  state
                  createdAt
                }
              }
            }
          }
        }
      }
    }
  }
}
''')


class CheckStatus(TypedDict, total=False):
    '''The result of a single check of a commit.'''
    state: State
    context: str
    createdAt: str
    repo: str
    pr: int
    commit_sha: str
    ci_name: str


def get_status_url(status: CheckStatus) -> str | None:
    '''Construct a useful URL for the given check, falling back to its PR.'''
    if (url := status.get('targetUrl')):
        return url
    try:
        return 'https://github.com/{repo}/pull/{pr}'.format(**status)
    except KeyError:
        return None


def get_check_statuses(client, repo: str, branch: str, checks: list[str],
                       names_table: dict[str, str]) \
        -> dict[str, list[CheckStatus]]:
    '''Yield {check: [status]} for all given checks on PRs in repo.'''
    owner, is_valid, repo_name = repo.partition('/')
    if not is_valid:
        raise ValueError('repository name must contain a slash')
    statuses: defaultdict[str, list[CheckStatus]] = defaultdict(list)
    response = client.execute(GET_PR_STATUSES_GRAPHQL, {
        'repoOwner': owner, 'repoName': repo_name, 'baseBranch': branch,
    })
    for pull in response['repository']['pullRequests']['nodes']:
        if pull['isDraft'] or pull['title'].startswith('[WIP]'):
            continue
        # We only ever get one commit in the response from GitHub.
        commit = pull['commits']['nodes'][0]['commit']
        contexts = ({c['context']: c for c in commit['status']['contexts']}
                    if commit['status'] else {})
        for check in checks:
            # Fallback to 'expected' status with sensible defaults.
            fallback = {'context': check, 'state': 'EXPECTED',
                        'createdAt': NOW.strftime(TIMEFORMAT)}
            statuses[check].append(contexts.get(check, fallback) | {
                'repo': repo,
                'pr': pull['number'],
                'commit_sha': commit['oid'],
                'ci_name': names_table[check],
            })
    return statuses
