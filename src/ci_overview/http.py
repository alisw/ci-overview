"""Create an HTTP server to serve web requests."""

from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from textwrap import dedent
import threading

from ci_overview.api_client import Client, make_client
from ci_overview._version import version


exit_event: threading.Event = threading.Event()
html_page: bytes = \
    b'<!doctype html><body><h2>Generating, please wait...</h2></body>'
metrics_page: bytes = b'# Generating, please wait...\n'


class Output: pass
class HtmlOutput(Output):
    '''Export the overview table as a HTML document.'''

    def begin(self: HtmlOutput) -> None:
        '''Output the HTML <head> element and initial boilerplate.'''
        print(dedent('''\
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8">
        <title>ALICE CI overview</title>
        <style type="text/css">
        body { font-family: sans-serif; margin: 0; padding: 1rem; }
        #key { padding: 0.5rem; }
        #key[open] { border: 0.15rem dashed #777; }
        #key summary { font-weight: bold; }
        .branch-name { font-family: monospace; font-size: 1.25rem;
                       font-style: italic; margin-left: 0.75rem; }
        .branch-name::before { content: "("; }
        .branch-name::after { content: ")"; }
        .check-name { margin-left: 1rem; }
        .empty { font-size: 0.875rem; color: #777; font-style: italic; }
        .table { margin-left: 1.75rem; display: flex; place-content: start;
                 flex-flow: row wrap; }
        .status { padding: 0.25rem; margin: 0.25rem; --status-color: currentColor;
                  border: 0.1rem solid transparent; color: var(--status-color); }
        .status a { display: block; color: inherit; }
        .status.recent { border-color: var(--status-color); }
        .status.EXPECTED { --status-color: #24292f; border-style: dotted; }
        .status.PENDING { --status-color: #bf8700; }
        .status.SUCCESS { --status-color: #1a7f37; }
        .status.ERROR { --status-color: #cf222e; }
        .status.FAILURE { --status-color: #cf222e; font-weight: bold; }
        </style>
        </head>
        <body>
        <h1>ALICE CI overview</h1>
        '''), dedent(f'''\
        <p>Document generated at {NOW.strftime(TIMEFORMAT)}. Statuses from the
           last <strong>{self.recent_hours:g} hours</strong>, i.e. newer than
           {self.recent_cutoff}, are marked as
           <span class="status recent">recent</span>.</p>
        '''), dedent('''\
        <details id="key"><summary>Explanation (click to expand)</summary>
        <p>The results of the check listed in each heading are shown for each
           pull request in a list.</p>
        <p>Results are ordered most recent first.</p>
        <p>Checks that completed after a set cutoff point (see the top of this
           document for the specific time) have a border around them,
           <span class="status recent">like this</span>.</p>
        <p>The colour coding works as follows:</p>
        <ul>
          <li><span class="status EXPECTED">#0000</span> is an "expected"
              status, which means that the CI has not picked up this PR at all
              yet for the respective check.</li>
          <li><span class="status PENDING">#0000</span> is a "pending" status,
              which means that the CI has picked this PR up, but the check has
              not yet completed.</li>
          <li><span class="status SUCCESS">#0000</span> is a successful status,
              i.e. this check has run and no errors were found.</li>
          <!--<li><span class="status FAILURE">#0000</span> is a failed status,
              which doesn't happen with the current CI system.</li>-->
          <li><span class="status ERROR">#0000</span> is an error status, which
              means that the check has run but a build error occurred.</li>
        </ul>
        </details>
        '''), sep='', end='', file=self.output_file)

    def repo_header(self: HtmlOutput, repo: str, branch: str) -> None:
        '''Output a heading with the repository and branch name.'''
        print(f'<h2>{repo} <span class="branch-name">{branch}</span></h2>',
              file=self.output_file)

    def check_header(self: HtmlOutput, check_name: str) -> None:
        '''Output the given check name.'''
        print(f'<h3 class="check-name">{check_name}</h3>',
              file=self.output_file)

    def empty_table(self: HtmlOutput) -> None:
        '''Output a helpful message for a table with no PRs.'''
        print('<div class="table empty">(no open non-draft PRs here)</div>',
              file=self.output_file)

    def overview_table(self: HtmlOutput, pr_statuses: list[Check]) -> None:
        '''Show a nicely formatted table of PR results for the given check.'''
        _, template = self.overview_table_prep(pr_statuses)
        print('<div class="table">',
              *(self.format_status(status, template.format(status['pr']))
                for status in pr_statuses),
              '</div>', sep='\n', file=self.output_file)

    def format_status(self: HtmlOutput, status: Check, text: str) -> str:
        '''Tag the given text as appropriate for the given status.

        If possible, the text is also hyperlinked to the document reporting
        check results.
        '''
        if (url := get_status_url(status)):
            text = f'<a href="{url}">{text}</a>'
        date = 'recent' if status['createdAt'] > self.recent_cutoff else 'old'
        return (f'<div class="status {status["state"]} {date}"'
                f' title="{status.get("createdAt", "")}">{text}</div>')

    def end(self: HtmlOutput) -> None:
        '''Close any open tags.'''
        print('</body></html>', file=self.output_file)


def generate_html(client: Client) -> bytes:
    return html_page


def generate_metrics(client: Client) -> bytes:
    return metrics_page


def regenerate_output() -> None:
    global html_page, metrics_page
    try:
        client = make_client()
    except SystemExit:  # TODO better exception
        exit_event.set()
        return
    metrics_page = generate_metrics(client)
    html_page = generate_html(client)
    while not exit_event.wait(60):
        metrics_page = generate_metrics(client)
        html_page = generate_html(client)


class CIOverviewServer(BaseHTTPRequestHandler):
    """Serve both a human-readable HTML page and Prometheus metrics."""
    server_version = f'alice-ci-overview/{version}'

    def do_HEAD(self: CIOverviewServer) -> None:
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html_page)))
            self.end_headers()
        elif self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(metrics_page)))
            self.end_headers()
        else:
            self.send_error(404, f'Nothing found at {self.path}!')

    def do_GET(self: CIOverviewServer) -> None:
        """Handle GET requests to any path."""
        self.do_HEAD()
        if self.path == '/':
            self.wfile.write(html_page)
        elif self.path == '/metrics':
            self.wfile.write(metrics_page)
        else:
            pass  # error already sent


def main() -> None:
    """Create and run the HTTP server."""
    background_update = threading.Thread(target=regenerate_output, name='background-update')
    background_update.start()
    with ThreadingHTTPServer(('127.0.0.1', 8000), CIOverviewServer) as server:
        serve = threading.Thread(target=server.serve_forever, name='server')
        serve.start()
        try:
            exit_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            exit_event.set()
            server.shutdown()
            serve.join()
            background_update.join()


if __name__ == '__main__':
    main()
