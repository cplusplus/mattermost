require('babel-polyfill');
require('isomorphic-fetch');
if (!global.WebSocket) {
    global.WebSocket = require('ws');
}

if (!String.prototype.format) {
    String.prototype.format = function() {
        var args = arguments;
        return this.replace(/{(\d+)}/g, function(match, number) {
            return typeof args[number] != 'undefined' ?
                args[number] :
                match;
        });
    };
}


class MessageFormatter {
    constructor(reference, info) {
        this.reference = reference
        this.info = info
    }

    formatMessage() {
        throw new Error("Not Yet Implemented");
    }

    createLink(text, url) {
        return '[{0}]({1})'.format(this.escapeText(text), url);
    }

    escapeText(text) {
        return text.replaceAll(['[', ']', '(', ')'], ['\\[', '\\]', '\\(', '\\)']);
    }

    getAuthors() {
        const authors = this.info.author.split(', ');
        const number_of_authors = authors.length;
        if (number_of_authors <= 2) {
            return authors.join(', ')
        } else {
            return '{0} et al.'.format(authors[0])
        }
    }

    getAudience() {
        function translateSubgroup(subgroup) {
            const map = {
                'Core': 'CWG',
                'Evolution': 'EWG',
                'Library': 'LWG',
                'Library Evolution': 'LEWG',
                'Direction Group': 'DG',
                'Library Evolution Incubator': 'LEWGI',
                'Evolution Incubator': 'EWGI',
            }

            return subgroup in map ? map[subgroup] : subgroup;
        }

        const subgroups = this.info.subgroup.split(', ')

        return [subgroups.map((subgroup) => translateSubgroup(subgroup))].join(', ');
    }

    githubComponent() {
        if (!('github_url' in this.info)) {
            return [];
        }

        const github_issue_no = this.info.github_url.match(/\/issues\/(\d+)/)[1];
        const github_link = 'Github issue: ' + this.createLink('#{0}'.format(github_issue_no), this.info.github_url);

        return [github_link];
    }

    relatedIssuesComponent() {
        if (!('issues' in this.info)) {
            return [];
        }

        const heading = this.info.issues.length == 1 ? 'Related issue: ' : 'Related issues: ';
        const related_issues = heading + this.info.issues.map((issue_reference) => this.createLink(issue_reference, 'https://wg21.link/{0}'.format(issue_reference))).join(', ');
        return [related_issues];
    }

    relatedPapersComponent() {
        if (!('papers' in this.info)) {
            return [];
        }

        const heading = this.info.papers.length == 1 ? 'Related paper: ' : 'Related papers: ';

        const related_papers = heading + this.info.papers.map((paper_reference) => this.createLink(paper_reference, 'https://wg21.link/{0}'.format(paper_reference))).join(', ');
        return [related_papers];
    }

    formatMessageComponents(components) {
        return components.join(' | ');
    }
}


class IssueMessageFormatter extends MessageFormatter {
    formatMessage() {
        return this.formatMessageComponents([':speech_balloon:',
            ...this.paperLinkComponent(),
            ...this.sectionComponent(),
            ...this.githubComponent(),
            ...this.relatedPapersComponent()
        ])
    }

    paperLinkComponent() {
        const title = this.info.title;

        let extra_info = ''
        if ('submitter' in this.info) {
            const submitter = this.info.submitter;
            extra_info += 'submitted by {0}'.format(submitter);
        }
        if ('date' in this.info) {
            const date = this.info.date;
            extra_info += ' ({0})'.format(date);
        }

        const text = '[{0}] {1}'.format(this.reference, title);
        const paper_link = this.createLink(text, this.info.long_link);
        return ['{0} {1}'.format(paper_link, extra_info)];
    }

    sectionComponent() {
        if (!('section' in this.info)) {
            return [];
        }

        const section = this.info.section;
        return ['Section: {0}'.format(section)];
    }
}


class PaperMessageFormatter extends MessageFormatter {
    formatMessage() {
        return this.formatMessageComponents([':rolled_up_newspaper:',
            ...this.paperLinkComponent(),
            ...this.githubComponent(),
            ...this.relatedIssuesComponent()
        ]);
    }

    paperLinkComponent() {
        const title = this.info.title;

        let text = '[{0}]'.format(this.reference);
        if ('subgroup' in this.info) {
            text += ' {0}:'.format(this.getAudience());
            text += ' {0}'.format(title);
        }

        let extra_info = ''
        if ('author' in this.info) {
            extra_info += ' by {0}'.format(this.getAuthors());
        }
        if ('date' in this.info) {
            const date = this.info.date;
            extra_info += ' ({0})'.format(date);
        }

        const paper_link = this.createLink(text, this.info.long_link);
        return ['{0} {1}'.format(paper_link, extra_info)];
    }
}


class EditorialMessageFormatter extends MessageFormatter {
    formatMessage() {
        return this.formatMessageComponents([':lower_left_ballpoint_pen: ',
            ...this.paperLinkComponent()
        ]);
    }

    paperLinkComponent() {
        const title = this.info.title;
        const text = '[{0}] {1}'.format(this.reference, title);
        const paper_link = this.createLink(text, this.info.long_link);
        return [paper_link];
    }
}


class StandingDocumentMessageFormatter extends MessageFormatter {
    formatMessage() {
        return this.formatMessageComponents([':compass:',
            ...this.paperLinkComponent()
        ]);
    }

    paperLinkComponent() {
        const title = this.info.title;
        const text = '[{0}] {1}'.format(this.reference, title);
        const paper_link = this.createLink(text, this.info.long_link);
        return [paper_link];
    }
}


class NotFoundMessageFormatter extends MessageFormatter {
    formatMessage() {
        return this.formatMessageComponents([':mag:',
            'Sorry, I could not find an issue or paper called `{0}` :worried:'.format(this.reference)
        ]);
    }
}


class MessageFormatterFactory {
    createFromInfo(reference, info) {
        const builders = {
            'issue': IssueMessageFormatter,
            'paper': PaperMessageFormatter,
            'editorial': EditorialMessageFormatter,
            'standing-document': StandingDocumentMessageFormatter,
        };

        const builder = info !== undefined ? builders[info['type']] : NotFoundMessageFormatter;

        return new builder(reference, info);
    }
}

class PaperBot {
    constructor(config) {
        this.initHealthCheckService();
        this.initPaperIndex();
        this.initCommands();
        this.initChatConnection(config);

        this.message_formatter_factory = new MessageFormatterFactory();
    }

    initCommands() {
        this.commands = {};
        this.registerCommand('help', this.handleHelpCommand);
        this.registerCommand('search', this.handleSearchCommand);
        this.registerCommand('version', this.handleVersionCommand);
    }

    registerCommand(token, handler) {
        this.commands[token] = (post, message, tokenized) => handler.bind(this)(post, message, tokenized);
    }

    initHealthCheckService() {
        const pjson = require('../package.json');
        this.launch_timestamp = new Date();

        const express = require('express')
        this.express = express()
        this.express.get("/health", (req, res) => this.handleHealthCheck(req, res));
        this.stats = {
            version: pjson.version,
            uptime: 0,
            chat: {
                interactions: 0,
                handled_events: 0,
                handled_posts: 0,
                ignored_posts: 0,
                posts_sent: 0,
            },
            api: {
                requests_sent: 0,
                responses_handled: 0,
            },
            paper_requests_handled: 0,
            commands_handled: 0,
            commands: {
                help: 0,
                search: 0,
                version: 0,
            },
            index: {
                update_checks_performed: 0,
                cache_hits: 0,
                cache_expirations: 0,
                updates_triggered: 0,
                updates_successful: 0,
                lookups: 0,
                index_rebuilt: 0,
                search_index_rebuilt: 0,
            },
            formattings_requested: 0,
            formattings_done: 0,
            formatting_errors: 0,
        }
        this.express.listen(3000)
    }

    initChatConnection(config) {
        const Client4 = require('../node_modules/mattermost-redux/client/client4.js').default;
        this.client = new Client4;
        this.wsClient = require('../node_modules/mattermost-redux/client/websocket_client.js').default;
        const {
            Post,
            PostList,
            PostSearchResults,
            OpenGraphMetadata
        } = require("../node_modules/mattermost-redux/types/posts");

        this.client.setUrl(config.apiUrl);
        this.client.setToken(config.token);
        this.client.setIncludeCookies(false);
        this.wsClient.initialize(config.token, {
            connectionUrl: config.websocketUrl
        });

        this.stats.api.requests_sent += 1;
        this.client.getMe().then((profile) => {
            this.stats.api.responses_handled += 1;
            this.me = profile;

            this.wsClient.setEventCallback((event) => this.handleNewPost(event));
        });
    }

    handleHealthCheck(req, res) {
        this.stats.uptime = new Date() - this.launch_timestamp;
        res.json(this.stats)
    }

    handleNewPost(event) {
        this.stats.chat.handled_events += 1;

        if (event.data.user_id == this.me.id) {
            return;
        }

        if (!('post' in event.data)) {
            return;
        }

        if (event.event != 'posted') {
            return;
        }

        this.stats.chat.handled_posts += 1;
        let post = JSON.parse(event.data.post);
        if (post.user_id == this.me.id) {
            return;
        }

        const message = post.message.trim();

        const bot_is_mentioned = message.includes("@{0}".format(this.me.username));
        if (bot_is_mentioned) {
            this.handleChatMessage(post);
            return;
        }

        this.stats.api.requests_sent += 1;
        this.client.getChannel(post.channel_id).then((channel) => {
            this.stats.api.responses_handled += 1;

            const is_direct_message = channel.type == 'D';
            if (!is_direct_message) {
                const contains_paper_reference_in_brackets = message.match(/\[((?:(C|E|LE?)WG|FS|SD|N|P|D|EDIT) ?\d+(R\d+)?)](?!\()/i) !== null;
                if (contains_paper_reference_in_brackets) {
                    this.handleBracketPaperRequest(post)
                    return;
                }

                this.stats.chat.ignored_posts += 1;
                return;
            }

            this.handleChatMessage(post);
        });

    }

    handleChatMessage(post) {
        const message = post.message.replace(/@[a-zA-z0-9_-]+/g, '').trim();
        const tokenized = message.split(/\b/).filter(token => token.trim().length != 0);

        if (tokenized.length == 0) {
            this.stats.chat.ignored_posts += 1;
            return;
        }

        const command_token = tokenized[0].toLowerCase();
        if (command_token in this.commands) {
            this.stats.commands_handled += 1;
            this.commands[command_token](post, message, tokenized);
            return;
        }

        this.handlePotentialPaperRequest(post);
    }

    respondTo(post, message) {
        this.stats.chat.posts_sent += 1;
        this.client.createPost({
            'message': message,
            'channel_id': post.channel_id,
            'root_id': post.root_id
        });
    }

    handleHelpCommand(post, message, tokenized) {
        this.stats.commands.help += 1;

        const help = (":book: | Usage: \"@{0} search [papers|issues|everything] <keywords>\"\n" +
            "                  or \"@{0} <Nxxxx|Pxxxx|PxxxxRx|Dxxxx|DxxxxRx|CWGxxx|EWGxxx|LWGxxx|LEWGxxx|FSxxx>\"\n" +
            "\n" +
            "Paperbot will also lookup any paper posted in square brackets, even without being mentioned.\n" +
            "In a DM with the paperbot only you do not need to mention it.").format(this.me.username);
        this.respondTo(post, help);
    }

    handleVersionCommand(post, message, tokenized) {
        this.stats.commands.version += 1;

        var pjson = require('../package.json');
        this.respondTo(post, 'Running PaperBot in Version {0}'.format(pjson.version));
    }

    handleSearchCommand(post, message, tokenized) {
        this.stats.commands.search += 1;

        if (tokenized.length < 2) {
            this.respondTo(post, "Invalid search command, see help for how to use the search.");
            return;
        }

        const [keywords, type_filter] = (() => {
            switch (tokenized[1]) {
                case 'papers':
                case 'paper':
                    return [tokenized.slice(2), 'paper'];
                case 'issues':
                case 'issue':
                    return [tokenized.slice(2), 'issue'];
                case 'everything':
                    return [tokenized.slice(2), undefined];
                default:
                    return [tokenized.slice(1), undefined];
            }
        })();

        this.doSearch(keywords, type_filter, post);
    }

    doSearch(keywords, type, post) {
        this.ensurePaperIndexUpdated().then(() => {
            const results = this.searchPapers(keywords, type);
            const displayed_results = results.slice(0, 15);
            const further_results = results.slice(15, 30);

            if (displayed_results.length == 0) {
                let reply = 'No results found for your search ';
                if (type !== undefined) {
                    reply += 'for **{0}s**'.format(type);
                } else {
                    reply += 'for all documents';
                }
                reply += ' with the keywords: *{0}*'.format(keywords.join(", "));
                this.respondTo(post, reply);
                return;
            }

            try {
                const result_list = displayed_results.map(
                        (result) => '1. {0}'
                        .format(this.message_formatter_factory
                            .createFromInfo(...this.getPaperInfoByRef(result['id']))
                            .formatMessage()))
                    .join('\n');

                let reply = results.length != 1 ? 'Found {0} results'.format(results.length) : '1 result';
                reply += ' for your search ';
                if (type !== undefined) {
                    reply += 'for **{0}s**'.format(type);
                } else {
                    reply += 'for all documents';
                }
                reply += ' with the keywords: *{0}*'.format(keywords.join(', '));

                if (results.length != displayed_results.length) {
                    reply += ', showing most recent {0} documents'.format(displayed_results.length);
                }
                reply += ':\n' + result_list;

                let shortLink = (id) => {
                    const [reference, info] = this.getPaperInfoByRef(id);
                    const long_link = info['long_link'];
                    return '[{0}]({1})'.format(reference, long_link);
                }

                if (further_results.length >= 1) {
                    const lo = displayed_results.length + 1;
                    const hi = lo + further_results.length - 1;
                    reply += '\nAlso ({0}-{1}): '.format(lo, hi) + further_results.map((result) => shortLink(result['id'])).join(', ');
                }

                this.respondTo(post, reply)
            } catch (e) {
                console.log(e);
                this.respondTo(post, 'An error occurred.');
            }
        });
    }

    handleBracketPaperRequest(post) {
        this.stats.chat.interactions += 1;

        const paper_request_in_brackets_regex = /\[((?:(C|E|LE?)WG|FS|SD|N|P|D|EDIT) ?\d+(R\d+)?)](?!\()/gi;
        const papers_requested = [...post.message.matchAll(paper_request_in_brackets_regex)].map(m => m[1]);
        this.handlePaperRequest(post, papers_requested, false);
    }

    handlePotentialPaperRequest(post) {
        this.stats.paper_requests_handled += 1;

        const paper_request_regex = /(?:(C|E|LE?)WG|FS|SD|N|P|D|EDIT) ?\d+(R\d+)?/gi;
        const papers_requested = [...post.message.matchAll(paper_request_regex)].map(m => m[0]);
        this.handlePaperRequest(post, papers_requested, true);
    }

    handlePaperRequest(post, papers_requested, bot_was_mentioned) {
        let papers = papers_requested.filter(function(value, index, array) {
            return array.indexOf(value) === index;
        });
        if (papers.length == 0) {
            this.stats.chat.ignored_posts += 1;
            return;
        }

        this.stats.paper_requests_handled += 1;

        if (!bot_was_mentioned && papers.length == 0) {
            return;
        }

        this.ensurePaperIndexUpdated().then(() => {
            const message = papers.map((ref) => this.getPaperInfoByRef(ref)).map(([reference, paper_info]) => {
                this.stats.formattings_requested += 1;
                try {
                    const formatter = this.message_formatter_factory.createFromInfo(reference, paper_info);
                    const formatted_message = formatter.formatMessage();
                    this.stats.formattings_done += 1;
                    return formatted_message;
                } catch {
                    this.stats.formatting_errors += 1;
                    return '*Error formatting response for {0}*'.format(reference);
                }
            }).join("\n");

            this.respondTo(post, message);
        });
    }

    initPaperIndex() {
        this.paper_index = {};
        this.doPaperIndexUpdate();
    }

    ensurePaperIndexUpdated() {
        this.stats.index.update_checks_performed += 1;

        const now = new Date();
        const cache_age = now - this.cache_timestamp;
        const cache_expired = cache_age > 180000; // 3 minutes

        if (!cache_expired) {
            this.stats.index.cache_hits += 1;
            return new Promise((resolve, reject) => {
                resolve();
            });
        }

        this.stats.index.cache_expirations += 1;
        return this.doPaperIndexUpdate();
    }

    doPaperIndexUpdate() {
        this.stats.index.updates_triggered += 1;

        return new Promise((resolve, reject) => {
            fetch(process.env.PAPER_INDEX_URL, {
                cache: "default"
            }).then((response) => {
                response.json().then((index_data) => {
                    this.stats.index.updates_successful += 1;

                    this.cache_timestamp = new Date();
                    this.rebuildIndex(index_data);
                    this.rebuildSearchIndex();
                    resolve();
                });
            });
        });
    }

    getPaperInfoByRef(ref) {
        this.stats.index.lookups += 1;

        const reference_or_id = ref.toUpperCase().replaceAll(' ', '');

        let extractReferenceAndKeyFromRefOrId = (reference_or_id) => {
            const reference_and_revision_regex = /(.+)R(\d+)/;
            const m = reference_and_revision_regex.exec(reference_or_id);
            if (m !== null) {
                return [m[1], reference_or_id];
            } else {
                return [reference_or_id, reference_or_id in this.paper_index ? this.paper_index[reference_or_id]['_'] : '_'];
            }
        };

        const [reference, key] = extractReferenceAndKeyFromRefOrId(reference_or_id);
        const result = reference in this.paper_index && key in this.paper_index[reference] ?
            [key, this.paper_index[reference][key]] :
            [reference_or_id, undefined];

        return result;
    }

    searchPapers(keywords, type) {
        let matchesSearch = (entry) => {
            if (type !== undefined && entry['type'] != type) {
                return false;
            }

            return keywords.map((keyword) => entry['keywords'].includes(keyword)).every(v => v === true);
        }

        keywords = keywords.map((kw) => kw.toLowerCase());
        const result = this.search_index.filter((entry) => matchesSearch(entry));
        result.sort((lhs, rhs) => rhs.date - lhs.date);
        return result;
    }

    rebuildIndex(index_payload) {
        const reference_and_revision_regex = /(.+)R(\d+)/;

        let extractReferenceAndRevisionFromRef = (id) => {
            const m = reference_and_revision_regex.exec(id);
            return m !== null ? [m[1], parseInt(m[2])] : [id, 0];
        }

        let updated_index = {};
        Object.entries(index_payload).forEach(([id, info]) => {
            const [reference, revision] = extractReferenceAndRevisionFromRef(id);
            if (!(reference in updated_index)) {
                updated_index[reference] = {};
            }

            updated_index[reference][id] = info;
            let [_, latest_revision] = '_' in updated_index[reference] ? extractReferenceAndRevisionFromRef(updated_index[reference]['_']) : [undefined, 0];
            if (revision >= latest_revision) {
                updated_index[reference]['_'] = id;
            }
        });

        this.paper_index = updated_index;
        this.stats.index.index_rebuilt += 1;
    }

    rebuildSearchIndex() {
        function getDate(entry) {
            const date_value = 'date' in entry ? entry['date'] : '1970-01-01';
            return Date.parse(date_value);
        }

        this.search_index = Object.entries(this.paper_index).map(([reference, document]) => {
            return {
                'id': reference,
                'type': document[document['_']]['type'],
                'date': getDate(document[document['_']]),
                'keywords': Object.entries(document).filter(([key, _]) => key != '_').map(([key, data]) => '{0} {1} {2} {3} {4}'.format(
                    key,
                    data['title'],
                    'section' in data ? data['section'] : '',
                    'submitter' in data ? data['submitter'] : '',
                    'author' in data ? data['author'] : '',
                )).join(' ').toLowerCase()
            }
        });

        this.stats.index.search_index_rebuilt += 1;
    }
}

require('dotenv').config()

let bot = new PaperBot({
    token: process.env.MATTERMOST_TOKEN,
    apiUrl: process.env.MATTERMOST_API_URL,
    websocketUrl: process.env.MATTERMOST_WEBSOCKER_URL,
})