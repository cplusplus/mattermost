# paperbot

## Quick Reference

Paperbot currently responds to the following commands:

| Command  | Description |
| ------------- | ------------- |
| `help`  | Responds with a short help message.  |
| `search [papers\|issues\|everything] <keywords...>`  |  Searches for papers, issues or both (the default) matching the given keywords. |
| `version` | Returns the version of the bot. |
| `uptime` | Responds with the uptime of the bot. |
| `updateindex` | Force updating of the paper index. |

In channels and in DMs with more than two accounts involved paperbot only responds either if mentioned in the message or if the paper number is put in square brackets, for example:
> @paperbot P1000 P2000

> [P1000] [P2000]

in DMs with the bot only, the bot does not need to be mentioned.

## Hosting Instructions

The bot is hosted using a custom Dockercontainer that can either be built and used directly or indirectly via the docker-compose file.

### Configuration

Before building the container you need to edit the configuration. This is done using environment variables. For exampel via dotenv:

```
cp example.env .env
```

Then set the `MATTERMOST_TOKEN` to the one for the bot.

### Creating and starting the container

After that creating/starting/stopping follows normal docker-compose procedure.

```
docker compose up -d
```

### Rebuilding the container

```
docker compose build --no-cache
```