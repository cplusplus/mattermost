import time

from datetime import datetime, timedelta
import re
from typing import Tuple, Dict, List
from abc import ABC, abstractmethod
import os
import sys

import requests
from dotenv import load_dotenv
from etag_cache import EtagCache
from mattermostdriver import Driver

load_dotenv()


class PaperIndex:
    request_method = 'GET'
    repository_url = os.getenv('PAPER_INDEX_URL')
    refresh_cooldown = timedelta(seconds=30)
    reference_and_revision_regex = re.compile(pattern=r'(.+)R(\d+)')

    def __init__(self):
        self._cache_object = EtagCache(dir_path=os.getenv('PAPER_INDEX_CACHE'))
        self._index = None
        self._timestamp_of_last_refresh = None
        self._try_refresh_index()

    def _try_refresh_index(self):
        headers = self._cache_object.add_etag(self.request_method, {}, self.repository_url)
        response = requests.request(self.request_method, self.repository_url, headers=headers)
        self._cache_object.save_etag(response)
        self._rebuild_index(self._cache_object.add_read_cache(response))
        self._rebuild_search_index()

    def _try_refresh_index_if_needed(self):
        now = datetime.now()
        refresh_no_earlier_than = self._timestamp_of_last_refresh + self.refresh_cooldown

        if refresh_no_earlier_than <= now:
            self._try_refresh_index()
            self._timestamp_of_last_refresh = now

    def _rebuild_index(self, index_payload: dict):
        def extract_reference__and_revision_from_id(id: str) -> Tuple[str, int]:
            m = self.reference_and_revision_regex.match(id)
            return (m.group(1), int(m.group(2))) if m \
                else (id, 0)

        updated_index = {}
        for id, info in index_payload.items():
            reference, revision = extract_reference__and_revision_from_id(id)
            if reference not in updated_index:
                updated_index[reference] = {}

            updated_index[reference][id] = info
            _, latest_revision = extract_reference__and_revision_from_id(updated_index[reference]['_']) \
                if '_' in updated_index[reference] else None, 0
            if revision >= latest_revision:
                updated_index[reference]['_'] = id

        self._index = updated_index

    def fetch_info_for(self, reference_or_id: str) -> Tuple[str, Dict]:
        def extract_reference_and_key_from_ref_or_id(reference_or_id: str) -> Tuple[str, str]:
            m = self.reference_and_revision_regex.match(reference_or_id)
            if m:
                return (m.group(1), reference_or_id)
            else:
                return reference_or_id, self._index[reference_or_id]['_'] \
                    if reference_or_id in self._index \
                    else '_'

        self._try_refresh_index()
        reference, key = extract_reference_and_key_from_ref_or_id(reference_or_id)
        return (key, self._index[reference][key]) \
            if reference in self._index and key in self._index[reference] \
            else (reference_or_id, None)

    def search(self, keywords: List, type: str | None = None):
        def matches_search(entry):
            return all([keyword in entry['keywords'] for keyword in keywords]) and \
                (type is None or entry['type'] == type)

        result = [entry for entry in self._search_index if matches_search(entry)]
        return sorted(result, key=lambda entry: entry['date'], reverse=True)

    def _rebuild_search_index(self):
        def get_date(entry):
            date_value = entry['date'] if 'date' in entry else ''
            accepted_formats = ['%Y-%m-%d', '%d %b %Y', '%d %B %Y', '%B %Y', '%d %B, %Y', '%d %b, %Y']
            for accepted_format in accepted_formats:
                try:
                    return datetime.strptime(date_value, accepted_format)
                except ValueError:
                    pass
            return datetime.strptime('1970-01-01', '%Y-%m-%d')

        self._search_index = [
            {
                'id': reference,
                'type': document[document['_']]['type'],
                'date': get_date(document[document['_']]),
                'keywords': ' '.join(['{} {} {} {} {}'.format(
                    key,
                    data['title'],
                    data['section'] if 'section' in data else '',
                    data['submitter'] if 'submitter' in data else '',
                    data['author'] if 'author' in data else '',
                ) for key, data in document.items()
                    if key != '_']).lower()
            }
            for reference, document in self._index.items()]


class MessageFormatter(ABC):
    def __init__(self, reference: str, info: Dict):
        self._reference = reference
        self._info = info

    @abstractmethod
    def format_message(self) -> str:
        pass

    def _create_link(self, text: str, url: str) -> str:
        return f'[{self._escape_text(text)}]({url})'

    def _escape_text(self, text: str) -> str:
        return text.replace('[', '\\[') \
            .replace(']', '\\]') \
            .replace('(', '\\(') \
            .replace(')', '\\)')

    def _get_authors(self) -> str:
        authors = self._info['author'].split(', ')
        number_of_authors = len(authors)
        if number_of_authors <= 2:
            return ', '.join(authors)
        else:
            return f'{authors[0]} et al.'

    def _get_audience(self) -> str:
        def translate_subgroup(subgroup: str) -> str:
            map = {
                'Core': 'CWG',
                'Evolution': 'EWG',
                'Library': 'LWG',
                'Library Evolution': 'LEWG',
                'Direction Group': 'DG',
                'Library Evolution Incubator': 'LEWGI',
                'Evolution Incubator': 'EWGI',
            }
            return map[subgroup] if subgroup in map else subgroup

        subgroups = self._info['subgroup'].split(', ')
        return ', '.join([translate_subgroup(subgroup) for subgroup in subgroups])

    def _github_component(self):
        if 'github_url' in self._info:
            github_issue_no = self.github_issue_no_regex.search(self._info['github_url']).group(1)
            github_link = 'Github issue: ' + self._create_link(f'#{github_issue_no}', self._info['github_url'])
            return [github_link]
        return []

    def _related_issues_component(self):
        if 'issues' in self._info:
            heading = 'Related issue: ' if len(self._info['issues']) == 1 \
                else 'Related issues: '
            related_issues = heading \
                             + ', '.join([self._create_link(issue_reference, f'https://wg21.link/{issue_reference}')
                                          for issue_reference in self._info['issues']])
            return [related_issues]
        return []

    def _related_papers_component(self):
        if 'papers' in self._info:
            heading = 'Related paper: ' if len(self._info['papers']) == 1 \
                else 'Related papers: '
            related_issues = heading \
                             + ', '.join([self._create_link(issue_reference, f'https://wg21.link/{issue_reference}')
                                          for issue_reference in self._info['papers']])
            return [related_issues]
        return []

    def _format_message_components(self, components):
        return ' | '.join(components)


class IssueMessageFormatter(MessageFormatter):
    def format_message(self) -> str:
        return self._format_message_components([':speech_balloon:',
                                                *self._paper_link_component(),
                                                *self._section_component(),
                                                *self._github_component(),
                                                *self._related_papers_component()])

    def _paper_link_component(self):
        title = self._info['title']
        submitter = self._info['submitter']

        text = f'[{self._reference}] {title}'

        extra_info = f'submitted by {submitter}'
        if 'date' in self._info:
            date = self._info['date']
            extra_info += f' ({date})'
        paper_link = self._create_link(text, self._info['long_link'])
        return [f'{paper_link} {extra_info}']

    def _section_component(self):
        if 'section' in self._info:
            section = self._info['section']
            return [f'Section: {section}']
        return []


class PaperMessageFormatter(MessageFormatter):
    github_issue_no_regex = re.compile(r'/issues/(\d+)')

    def format_message(self) -> str:
        return self._format_message_components([':rolled_up_newspaper:',
                                                *self._paper_link_component(),
                                                *self._github_component(),
                                                *self._related_issues_component()])

    def _paper_link_component(self):
        title = self._info['title']

        text = f'[{self._reference}]'

        if 'subgroup' in self._info:
            text += f' {self._get_audience()}:'
        text += f' {title}'

        extra_info = ''
        if 'author' in self._info:
            extra_info += f' by {self._get_authors()}'

        if 'date' in self._info:
            date = self._info['date']
            extra_info += f' ({date})'
        paper_link = self._create_link(text, self._info['long_link'])
        return [f'{paper_link}{extra_info}']


class EditorialMessageFormatter(MessageFormatter):
    def format_message(self) -> str:
        return self._format_message_components([':lower_left_ballpoint_pen: ',
                                                *self._paper_link_component()])

    def _paper_link_component(self):
        title = self._info['title']

        text = f'[{self._reference}] {title}'
        paper_link = self._create_link(text, self._info['long_link'])
        return [paper_link]


class StandingDocumentMessageFormatter(MessageFormatter):
    def format_message(self) -> str:
        return self._format_message_components([':compass:',
                                                *self._paper_link_component()])

    def _paper_link_component(self):
        title = self._info['title']

        text = f'[{self._reference}] {title}'
        paper_link = self._create_link(text, self._info['long_link'])
        return [paper_link]


class NotFoundMessageFormatter(MessageFormatter):
    def format_message(self) -> str:
        return self._format_message_components([':mag:',
                                                f'Sorry, I could not find an issue or paper called `{self._reference}` :worried:'])


class MessageFormatterFactory:
    def create_from_info(self, reference: str, info: Dict | None) -> MessageFormatter:
        builder = {
            'issue': IssueMessageFormatter,
            'paper': PaperMessageFormatter,
            'editorial': EditorialMessageFormatter,
            'standing-document': StandingDocumentMessageFormatter,
        }[info['type']] if info is not None else NotFoundMessageFormatter

        return builder(reference, info)


class ChatMessageService:
    mattermost_url = os.getenv('MATTERMOST_URL')
    mattermost_port = int(os.getenv('MATTERMOST_PORT'))
    mattermost_scheme = os.getenv('MATTERMOST_SCHEME')
    mattermost_token = os.getenv('MATTERMOST_TOKEN')
    mattermost_channel_cache_dir = os.getenv('MATTERMOST_CHANNEL_CACHE')

    def __init__(self):
        self._driver = Driver(options={
            'url': self.mattermost_url,
            'token': self.mattermost_token,
            'scheme': self.mattermost_scheme,
            'port': self.mattermost_port,
            'debug': False,
        })
        self._driver.login()
        self._me = self._driver.users.get_user(user_id='me')
        self._initialize_from_cache()
        self._teams = []
        self._channels = []
        self._read_channel_list()

    def read_posts(self):
        self._update_channel_list_if_needed()

        posts = [post
                 for channel in self._channels
                 for post in self._read_messages_from_channel(channel).values()]
        return posts

    def _initialize_from_cache(self):
        os.makedirs(self.mattermost_channel_cache_dir, exist_ok=True)

        channel_cursors = {}
        for filename in os.listdir(self.mattermost_channel_cache_dir):
            channel_cursors[filename] = open(os.path.join(self.mattermost_channel_cache_dir, filename), mode="rt") \
                .readline()

        self._channel_cursors = channel_cursors

    def _read_channel_list(self):
        self._teams = self._driver.teams.get_user_teams(user_id=self._me['id'])
        updated_channels_list = [channel
                                 for team in self._teams
                                 for channel in
                                 self._driver.channels.get_channels_for_user(user_id=self._me['id'],
                                                                             team_id=team['id'])]

        channel_ids_after_update = set([channel['id'] for channel in updated_channels_list])
        channel_ids_before_update = set([channel['id'] for channel in self._channels])
        self._last_channel_update = datetime.now()
        self._channels = updated_channels_list

        channels_left = channel_ids_before_update - channel_ids_after_update
        channels_joined = channel_ids_after_update - channel_ids_before_update
        self._do_channel_join_leave_actions(channels_joined, channels_left)

    def _update_channel_list_if_needed(self):
        now = datetime.now()
        next_update_due = self._last_channel_update + timedelta(minutes=5)
        if next_update_due <= now:
            self._read_channel_list()

    def _read_messages_from_channel(self, channel):
        params = {
            'per_page': 5,
        }
        if channel['id'] in self._channel_cursors:
            params['after'] = self._channel_cursors[channel['id']]
        channel_update = self._driver.posts.get_posts_for_channel(channel_id=channel['id'], params=params)

        if len(channel_update['posts'].keys()) >= 1:
            self._update_channel_cursor(channel, channel_update)
        return channel_update['posts']

    def _update_channel_cursor(self, channel, channel_update):
        after_post_id = channel_update['next_post_id'] if channel_update['has_next'] else channel_update['order'][0]
        self._channel_cursors[channel['id']] = after_post_id
        print(after_post_id, file=open(os.path.join(self.mattermost_channel_cache_dir, channel['id']), 'wt'), end='')

    def _do_channel_join_leave_actions(self, channels_joined, channels_left):
        for channel_id in channels_joined:
            channel_name = next(filter(lambda channel: channel['id'] == channel_id, self._channels))['display_name'] \
                           or '(none)'
            channel_members = self._driver.channels.get_channel_members(channel_id=channel_id)
            print(f'Joined channel {channel_id} (name: {channel_name}, members: {len(channel_members)})')

        for channel_id in channels_left:
            print(f'Left channel {channel_id}')

    def me(self):
        return self._me

    def reply_to(self, original_post, reply):
        print(original_post)
        self._driver.posts.create_post(options={
            'channel_id': original_post['channel_id'],
            'root_id': original_post['root_id'] or original_post['id'],
            'message': reply
        })


class ChatCommandHandler:
    split_command_token_regex = re.compile(r'[\s,\.;:!\?]+')
    reference_mention_regex = re.compile(r'(?:(C|E|LE?)WG|FS|SD|N|P|D|EDIT) ?\d+(R\d+)?')
    # r'(?:CWG|D|EDIT|EWG|FS|LEWG|LWG|SD|N|P) ?\d+(R\d+)?'
    reference_brackets_regex = re.compile(r'\[((?:(C|E|LE?)WG|FS|SD|N|P|D|EDIT) ?\d+(R\d+)?)]')

    def __init__(self, chat_message_service: ChatMessageService, paper_index: PaperIndex):
        self._chat_service = chat_message_service
        self._paper_index = paper_index
        self._formatter_factory = MessageFormatterFactory()

    def run_once(self):
        def filter_posts(message: Dict) -> bool:
            is_update_message = message['update_at'] != message['create_at']

            is_message_from_bot = message['user_id'] == self._chat_service.me()['id']

            a_minute_ago = datetime.now() - timedelta(minutes=1)
            posted_at = datetime.fromtimestamp(message['create_at'] / 1000.0)
            posted_more_than_a_minute_ago = posted_at < a_minute_ago

            is_message_in_thread = message['root_id'] != ''

            return not (
                    is_update_message or is_message_from_bot or posted_more_than_a_minute_ago or is_message_in_thread)

        for unread_post in filter(filter_posts, self._chat_service.read_posts()):
            username_of_bot = self._chat_service.me()['username']

            user = self._chat_service._driver.users.get_user(user_id=unread_post['user_id'])

            bot_is_mentioned_in_message = f'@{username_of_bot}' in unread_post['message']
            if bot_is_mentioned_in_message:
                self._log_request_to_bot(unread_post, user)

            message_starts_with_mentioning_bot = unread_post['message'].startswith(f'@{username_of_bot}')
            if message_starts_with_mentioning_bot:
                self._handle_bot_command(unread_post, user)
                return

            self._handle_paper_request([], unread_post, user, False)

    def _handle_bot_command(self, unread_post, user):
        tokens = list(filter(
            lambda token: len(token.strip()) >= 1,
            self.split_command_token_regex.split(unread_post['message'])))

        command = tokens[1] if len(tokens) >= 2 else '_'
        command_handlers = {
            'help': self._do_help,
            'kill': self._do_kill,
            'search': self._do_search,
            '_': self._handle_paper_request,
        }
        handler = command_handlers[command if command in command_handlers else '_']
        handler(tokens, unread_post, user)

    def _do_help(self, tokens, post, user):
        username = user['username']
        nickname = user['nickname'] or '(none)'
        display_name = '{} {}'.format(user['first_name'], user['last_name']) if user['first_name'] else '(none)'
        print(f'Help requested by {display_name} - {nickname} ({username})')

        username_of_bot = self._chat_service.me()['username']
        reply = f':book: | Usage: "@{username_of_bot} search [papers|issues|everything] <keywords>"\n' \
                f'\t\t\t\tor "@{username_of_bot} <Nxxxx|Pxxxx|PxxxxRx|Dxxxx|DxxxxRx|CWGxxx|EWGxxx|LWGxxx|LEWGxxx|FSxxx>"\n' \
                f'\n' \
                f'{username_of_bot} will also lookup any paper posted in square brackets, even without being mentioned.'

        self._chat_service.reply_to(post, reply)

    def _handle_paper_request(self, tokens, post, user, collect_references_without_brackets=True):
        def deduplicate(references):
            return set([requested_reference.replace(' ', '') for requested_reference in references])

        references = self._collect_references_from_message(post, collect_references_without_brackets)

        reply_components = []
        for requested_reference in deduplicate(references):
            try:
                reply_components.append(self._formatter_factory.create_from_info(
                    *self._paper_index.fetch_info_for(requested_reference))
                                        .format_message())
            except KeyError:
                print(f'Formatting document {requested_reference} failed')

        username = user['username']
        nickname = user['nickname'] or '(none)'
        display_name = '{} {}'.format(user['first_name'], user['last_name']) if user['first_name'] else '(none)'
        message = '\n'.join(reply_components)

        self._chat_service.reply_to(post, message)

    def _log_request_to_bot(self, post, user):
        channel = next(filter(lambda channel: channel['id'] == post['channel_id'], self._chat_service._channels))
        is_direct_message_channel = channel['type'] == 'D'

        if is_direct_message_channel and False:  # TODO: remove bypass
            return

        channel_name = channel['display_name'] or '(none)'
        channel_id = channel['id']
        message = post['message']

        username = user['username']
        nickname = user['nickname'] or '(none)'
        display_name = '{} {}'.format(user['first_name'], user['last_name']) if user['first_name'] else '(none)'

        print(
            f'{display_name} - {nickname} ({username}) mentioned the bot in channel {channel_name} ({channel_id}) with message: {message}')

    def _collect_references_from_message(self, post, collect_references_without_brackets=False):
        references = []
        if collect_references_without_brackets:
            result = self.reference_mention_regex.finditer(post['message'].upper())
            for match in result:
                references.append(match.group())

        result = self.reference_brackets_regex.finditer(post['message'].upper())
        for match in result:
            references.append(match.group(1))

        return references

    def _do_kill(self, tokens, post, user):
        operators = ['tahonermann',
                     'sbuettner']

        if user['username'] not in operators:
            print('Ignoring terminating request')
            return

        username = user['username']
        nickname = user['nickname'] or '(none)'
        display_name = '{} {}'.format(user['first_name'], user['last_name']) if user['first_name'] else '(none)'

        print(f'Terminating paperbot after user request from {display_name} - {nickname} ({username})')
        sys.exit(1)

    def _do_search(self, tokens, post, user):
        print(tokens)

        if tokens[2] == 'papers':
            self._do_search_impl(tokens[3:], 'paper', post, user)
        elif tokens[2] == 'issues':
            self._do_search_impl(tokens[3:], 'issue', post, user)
        elif tokens[2] == 'everything':
            self._do_search_impl(tokens[3:], None, post, user)
        else:
            self._do_search_impl(tokens[2:], None, post, user)

    def _do_search_impl(self, keywords, type, post, user):
        results = self._paper_index.search(keywords, type=type)
        displayed_results = results[:15] if len(results) > 15 else results

        if len(displayed_results) == 0:
            self._chat_service.reply_to(post, 'No results found.')
            return

        try:
            result_list = '\n'.join([
                '1. {}'.format(
                    self._formatter_factory.create_from_info(
                        *self._paper_index.fetch_info_for(result['id']))
                    .format_message())
                for result in displayed_results])

            reply = f'{len(results)} results for your query'
            if len(results) != len(displayed_results):
                reply += f', showing most recent {len(displayed_results)}'
            reply += ':\n' + result_list

            self._chat_service.reply_to(post, reply)
        except KeyError:
            print(f'Formatting of one or multiple documents failed', displayed_results)
            self._chat_service.reply_to(post, 'An error occurred.')


def main():
    paper_index = PaperIndex()
    chat_message_service = ChatMessageService()

    chat_command_manager = ChatCommandHandler(chat_message_service=chat_message_service,
                                              paper_index=paper_index)

    while True:
        chat_command_manager.run_once()
        time.sleep(1)


main()
