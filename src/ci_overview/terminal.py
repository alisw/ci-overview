"""Show an overview of the CI system in the user's terminal."""

from __future__ import annotations
import itertools as it
from shutil import get_terminal_size
from collections.abc import Iterable   # for type checking

from ci_overview.pull_requests import CheckStatus


class Output:
    pass


class TextOutput(Output):
    '''Show the overview on the terminal in nice colours.'''
    INDENT: str = '  '
    SEPARATOR: str = '  '

    def repo_header(self: TextOutput, repo: str, branch: str) -> None:
        '''Format repo bold and underlined, and italicize branch.'''
        print(f'\033[4;1m{repo}\033[0m  \033[3m({branch})\033[0m',
              file=self.output_file)

    def check_header(self: TextOutput, check_name: str) -> None:
        '''Format the given check name by underlining.'''
        print(f'{self.INDENT}\033[4m{check_name}\033[0m',
              file=self.output_file)

    def empty_table(self: TextOutput) -> None:
        '''Create a helpful message for a table with no PRs.'''
        print(self.INDENT, self.INDENT,
              '\033[3;90m(no open non-draft PRs here)\033[0m',
              sep='', end='\n\n', file=self.output_file)

    def overview_table(self: TextOutput, pr_statuses: list[CheckStatus]) -> None:
        '''Print a nicely formatted table of PR results for the given check.'''
        prnum_len, template = self.overview_table_prep(pr_statuses)
        terminal_width = get_terminal_size((80, 1)).columns
        items_per_row = ((terminal_width - 2*len(self.INDENT) + len(self.SEPARATOR)) //
                         (len('#') + prnum_len + len(self.SEPARATOR)))
        for _, row in it.groupby(enumerate(pr_statuses),
                                 key=lambda tpl: tpl[0] // items_per_row):
            self.table_row(((status, template.format(status['pr']))
                            for _, status in row))
        print(file=self.output_file)

    def table_row(self: TextOutput,
                  statuses_and_text: Iterable[tuple[CheckStatus, str]]) -> None:
        '''Format each text for its accompanying status and optional URL.'''
        print(self.INDENT, self.INDENT, sep='', end='', file=self.output_file)
        print(*(self.format_status(status, text)
                for status, text in statuses_and_text),
              sep=self.SEPARATOR, file=self.output_file)

    def format_status(self: TextOutput, status: CheckStatus, text: str) -> str:
        '''Color the given text as appropriate for the given status.

        If possible, the text is also formatted as a hyperlink to the document
        reporting check results.
        '''
        ansi_escaped = ''
        url = get_status_url(status)
        if url:
            ansi_escaped += '\033]8;;' + url + '\033\\'  # opening URL code

        ansi_escaped += '\033[' + {   # start opening color code
            'PENDING': '33',    # yellow
            'EXPECTED': '90',   # gray (bright black)
            'SUCCESS': '32',    # green
            'ERROR': '31',      # red
            'FAILURE': '31;1',  # bold red
        }[status['state']]

        if status['createdAt'] > self.recent_cutoff:
            ansi_escaped += ';7'  # reverse video -- swap fore- and background

        ansi_escaped += 'm' + text   # finish color code and append text
        if url:
            ansi_escaped += '\033]8;;\033\\'  # closing URL code
        return ansi_escaped + '\033[0m'  # closing color code
