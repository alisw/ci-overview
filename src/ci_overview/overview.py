'''Show an overview of what CI checks are failing or succeeding.

The overview links to check results in supporting terminals.
'''

import argparse
import glob
import itertools as it
import math
import os
import os.path
import shutil
from collections import defaultdict
from collections.abc import Iterable, Mapping   # for type checking
from datetime import datetime, timedelta
from textwrap import dedent
from typing import Optional, Union, Literal, Final, TypedDict

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from graphql.language.ast import DocumentNode
from alibot_helpers.utilities import parse_env_file


DEFAULTENV: Final[str] = 'DEFAULTS.env'
TIMEFORMAT: Final[str] = '%Y-%m-%dT%H:%M:%SZ'
NOW: Final[datetime] = datetime.utcnow()
INDENT: Final[str] = '  '
SEPARATOR: Final[str] = '  '
GET_PR_STATUSES_GRAPHQL: Final[DocumentNode] = gql('''\
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


State = Union[Literal['EXPECTED'], Literal['ERROR'], Literal['FAILURE'],
              Literal['PENDING'], Literal['SUCCESS']]
VALID_STATUSES: Final[tuple[State, ...]] = \
    'EXPECTED', 'PENDING', 'FAILURE', 'ERROR', 'SUCCESS'


class Check(TypedDict, total=False):
    '''The result of a single check of a commit.'''
    state: State
    context: str
    createdAt: str
    repo: str
    pr: int
    commit_sha: str
    ci_name: str


def get_check_statuses(client, repo: str, branch: str, checks: list[str],
                       names_table: Mapping[str, str]) \
        -> Mapping[str, list[Check]]:
    '''Yield {check: [status]} for all given checks on PRs in repo.'''
    owner, is_valid, repo_name = repo.partition('/')
    if not is_valid:
        raise ValueError('repository name must contain a slash')
    statuses: defaultdict[str, list[Check]] = defaultdict(list)
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


def get_all_checks(defs_dir: str, roles: list[str], containers: list[str],
                   repos: list[str], checks: list[str]) \
        -> tuple[Mapping[tuple[str, str], list[str]], Mapping[str, str]]:
    '''Parse .env files and return checks in each repo, plus a name dict.

    The name dict translates user-visible check names to internal names used in
    the result URL.
    '''
    name_table: Mapping[str, str] = {}
    all_checks: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for env_path in glob.glob(os.path.join(defs_dir, '*', '*', '*.env')):
        if env_path.endswith(os.sep + DEFAULTENV):
            continue
        check = {}
        role, docker, env = os.path.relpath(env_path, defs_dir).split(os.sep)
        if roles and role not in roles:
            continue
        if containers and docker not in containers:
            continue
        for envpath in (os.path.join(defs_dir, DEFAULTENV),
                        os.path.join(defs_dir, role, DEFAULTENV),
                        os.path.join(defs_dir, role, docker, DEFAULTENV),
                        os.path.join(defs_dir, role, docker, env)):
            if os.path.exists(envpath):
                check.update(parse_env_file(envpath))
        repo, branch, name = \
            check['PR_REPO'], check['PR_BRANCH'], check['CHECK_NAME']
        if repos and repo not in repos:
            continue
        if checks and name not in checks:
            continue
        name_table[name] = check['CI_NAME']
        all_checks[(repo, branch)].append(name)
    return all_checks, name_table


def output_check_table(pr_statuses: list[Check], recent_days: int) -> None:
    '''Print a nicely formatted table of PR results for the given check.'''
    pr_statuses.sort(key=lambda c: c['createdAt'], reverse=True)
    prnum_len = 1 + math.floor(math.log10(max(c['pr'] for c in pr_statuses)))
    terminal_width = shutil.get_terminal_size((80, 1)).columns
    items_per_row = ((terminal_width - 2*len(INDENT) + len(SEPARATOR)) //
                     (len('#') + prnum_len + len(SEPARATOR)))
    for _, row in it.groupby(enumerate(pr_statuses),
                             key=lambda tpl: tpl[0] // items_per_row):
        print(format_table_row((
            (status, f'#{{:{prnum_len}d}}'.format(status['pr']))
            for _, status in row
        ), recent_days))


def format_status(status: Check, text: str, recent_days: int) -> str:
    '''Color the given text as appropriate for the given status.

    If possible, the text is also formatted as a hyperlink to the document
    reporting check results.
    '''
    ansi_escaped = ''
    url: Optional[str] = None
    # If the check is pending or expected, there won't be a result yet.
    if status['state'] in ('SUCCESS', 'FAILURE', 'ERROR'):
        try:
            url = '/'.join([
                'https://ali-ci.cern.ch/alice-build-logs', status["repo"],
                str(status["pr"]), status["commit_sha"], status["ci_name"],
                'pretty.html'
            ])
        except KeyError:
            pass
    if url:
        ansi_escaped += '\033]8;;' + url + '\033\\'  # opening URL code

    ansi_escaped += '\033[' + {   # start opening color code
        'PENDING': '33',   # yellow
        'EXPECTED': '35',  # magenta
        'SUCCESS': '32',   # green
        'FAILURE': '31',   # red
        'ERROR': '31;1',   # bold red
    }[status['state']]

    recent_cutoff = (NOW - timedelta(days=recent_days)).strftime(TIMEFORMAT)
    if status['createdAt'] > recent_cutoff:
        ansi_escaped += ';7'  # reverse video -- swap foreground and background

    ansi_escaped += 'm' + text   # finish opening color code and append text
    if url:
        ansi_escaped += '\033]8;;\033\\'  # closing URL code
    return ansi_escaped + '\033[0m'  # closing color code


def format_repo_header(repo: str, branch: str) -> str:
    '''Format repo bold and underlined, and italicize branch.'''
    return f'\033[4;1m{repo}\033[0m  \033[3m({branch})\033[0m'


def format_check_header(check_name: str) -> str:
    '''Format the given check name by underlining.'''
    return f'{INDENT}\033[4m{check_name}\033[0m'


def format_table_row(statuses_and_text: Iterable[tuple[Check, str]],
                     recent_days: int) -> str:
    '''Format each text for its accompanying status and optional URL.'''
    return 2*INDENT + SEPARATOR.join(format_status(status, text, recent_days)
                                     for status, text in statuses_and_text)


def format_empty_table():
    '''Create a helpful message for a table with no PRs.'''
    return 2*INDENT + '\033[3;90m(no open non-draft PRs here)\033[0m'


def main(args: argparse.Namespace) -> None:
    '''Main entry point.'''
    client = Client(
        transport=AIOHTTPTransport(
            url='https://api.github.com/graphql',
            headers={'Authorization': 'bearer ' + os.environ['GITHUB_TOKEN']}),
        fetch_schema_from_transport=True)
    all_checks, names = \
        get_all_checks(args.definitions_dir, args.roles,
                       args.containers, args.repos, args.checks)
    for (repo, branch), checks in sorted(all_checks.items()):
        print(format_repo_header(repo, branch))
        statuses = get_check_statuses(client, repo, branch, checks, names)
        for check in sorted(checks):
            print(format_check_header(check))
            if statuses[check]:
                output_check_table(statuses[check], args.recent_days)
            else:
                print(format_empty_table())
            print()


def parse_args() -> argparse.Namespace:
    '''Parse and return command-line args.'''
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent('''\
        This script needs a GITHUB_TOKEN environment variable.

        Key to the output:
        {repo_header}
        {check_header}
        {recent_table_row}
        {old_table_row}

        "Expected" means no builder has picked the check up yet. Draft PRs
        (those marked as drafts and those with "[WIP]" in the title) are not
        shown. Read tables left to right, then down.
        ''').format(
            repo_header=format_repo_header('owner/repository', 'base branch'),
            check_header=format_check_header('check name'),
            recent_table_row=format_table_row((
                ({'state': status, 'createdAt': NOW.strftime(TIMEFORMAT)},
                 status.lower() + ' (recent)')
                for status in VALID_STATUSES
            ), 2),
            old_table_row=format_table_row((
                ({'state': status,
                  'createdAt': (NOW - timedelta(days=1)).strftime(TIMEFORMAT)},
                 status.lower() + ' (older) ')
                for status in VALID_STATUSES
            ), 0)))

    parser.add_argument(
        '--definitions-dir', metavar='DIR', default='ali-bot/ci/repo-config',
        help=('directory where .env files are located in a hierarchy; expects '
              'a directory structure of the form DIR/ROLE/CONTAINER/*.env '
              '(default %(default)s)'))
    parser.add_argument(
        '-t', '--recent-days', metavar='DAYS', type=int, default=1,
        help=('consider check results from the last %(metavar)s days recent '
              '(these are printed in reverse video; default %(default)d)'))

    filtering = parser.add_argument_group('filter displayed checks', dedent('''\
    Each filtering argument can be given multiple times. If no filtering
    arguments are given, all known checks are shown in the output.

    Filtering arguments can be combined. If multiple are given (possibly
    multiple times each), the criteria are OR-ed together. For example, "-c
    check1 -r repo1 -r repo2" would show an overview of check1 (in any repo),
    in addition to all checks in repo1 or repo2.
    '''))
    filtering.add_argument(
        '-m', '--mesos-role', action='append', metavar='ROLE', dest='roles',
        default=[], help='include checks running under this Mesos role')
    filtering.add_argument(
        '-d', '--docker-container', action='append', metavar='CONTAINER',
        dest='containers', default=[],
        help=('include checks running inside this Docker container (use the '
              'short name only, e.g. alisw/slc8-builder:latest -> slc8)'))
    filtering.add_argument(
        '-r', '--repo', action='append', metavar='USER/REPO', dest='repos',
        default=[],
        help=('include checks for this repository (of the form '
              "<user>/<repository>; don't include github.com)"))
    filtering.add_argument(
        '-c', '--check', action='append', metavar='NAME', dest='checks',
        default=[],
        help=('include the specific named check (use the name as it appears '
              'on GitHub, e.g. build/O2/o2)'))

    args = parser.parse_args()
    if 'GITHUB_TOKEN' not in os.environ:
        parser.error('GITHUB_TOKEN environment variable is required')
    return args


if __name__ == '__main__':
    main(parse_args())
