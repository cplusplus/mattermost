import time

import requests
from datetime import datetime, timedelta
import re
from typing import Tuple, Dict
from abc import ABC, abstractmethod
import os

from dotenv import load_dotenv
from etag_cache import EtagCache
from mattermostdriver import Driver

load_dotenv()


class PaperRepository:
    request_method = 'GET'
    repository_url = os.getenv('PAPER_INDEX_URL')
    refresh_cooldown = timedelta(seconds=30)
    reference_and_revision_regex = re.compile(pattern=r'(.+)R(\d+)')

    def __init__(self):
        self._cache_object = EtagCache(dir_path=os.getenv('PAPER_INDEX_CACHE'))
        self._index = None
        self._timestamp_of_last_refresh = None

    def _try_refresh_index(self):
        headers = self._cache_object.add_etag(self.request_method, {}, self.repository_url)
        response = requests.request(self.request_method, self.repository_url, headers=headers)
        self._cache_object.save_etag(response)
        self._rebuild_index(self._cache_object.add_read_cache(response))

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
        return self._format_message_components([':fire:',
                                                *self._paper_link_component(),
                                                *self._section_component(),
                                                *self._github_component(),
                                                *self._related_papers_component()])

    def _paper_link_component(self):
        title = self._info['title']
        submitter = self._info['submitter']

        text = f'[{self._reference}] {title} submitted by {submitter}'
        if 'date' in self._info:
            date = self._info['date']
            text += f' ({date})'
        paper_link = self._create_link(text, self._info['long_link'])
        return [paper_link]

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

        text += f' {title} by {self._get_authors()}'

        if 'date' in self._info:
            date = self._info['date']
            text += f' ({date})'
        paper_link = self._create_link(text, self._info['long_link'])
        return [paper_link]


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
        return self._format_message_components([':cpp:',
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
        self._channels = []
        self._read_channel_list()

    def read_messages(self):
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
        teams = self._driver.teams.get_user_teams(user_id=self._me['id'])
        updated_channels_list = [channel
                                 for team in teams
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
            print(f'Joined channel {channel_id}')

        for channel_id in channels_left:
            print(f'Left channel {channel_id}')


repository = PaperRepository()
formatter_factory = MessageFormatterFactory()

chat_message_service = ChatMessageService()

reference_mention_regex = re.compile(r'(?:CWG|D|EDIT|EWG|FS|LEWG|LWG|SD|N|P) ?\d+(R\d+)?')
reference_brackets_regex = re.compile(r'\[((?:CWG|D|EDIT|EWG|FS|LEWG|LWG|SD|N|P) ?\d+(R\d+)?)\]')

while True:
    posts = chat_message_service.read_messages()
    for post in posts:
        if post['update_at'] != post['create_at']:
            continue

        if post['user_id'] == chat_message_service._me['id']:
            continue

        a_minute_ago = datetime.now() - timedelta(minutes=1)
        created_more_than_a_minute_ago = post['create_at'] < a_minute_ago
        if created_more_than_a_minute_ago:
            continue

        requested_references = []

        user = chat_message_service._driver.users.get_user(user_id=post['user_id'])
        username = user['username']
        nickname = user['nickname']

        bot_username = chat_message_service._me['username']
        if f'@{bot_username}' in post['message']:
            channel = next(filter(lambda channel: channel['id'] == post['channel_id'], chat_message_service._channels))
            is_direct_message_channel = channel['type'] == 'D'

            if not is_direct_message_channel or True:
                channel_name = channel['display_name']
                channel_id = channel['id']

                message = post['message']

                print(f'{nickname} ({username}) mentioned {bot_username} in channel {channel_name} ({channel_id}) with message: {message}')

        if post['message'].startswith(f'@{bot_username}'):
            result = reference_mention_regex.finditer(post['message'].upper())
            for match in result:
                requested_references.append(match.group())

        result = reference_brackets_regex.finditer(post['message'].upper())
        for match in result:
            requested_references.append(match.group(1))

        for requested_reference in set([requested_reference.replace(' ', '') for requested_reference in requested_references]):
            message = formatter_factory.create_from_info(*repository.fetch_info_for(requested_reference)) \
                .format_message()
            chat_message_service._driver.posts.create_post(options={
                'channel_id': post['channel_id'],
                'root_id': post['id'],
                'message': message,
            })
            print(f'Responding to {nickname} ({username}) with message: {message}')

    time.sleep(1)
