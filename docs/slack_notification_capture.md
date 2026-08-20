# Slack Windows notification capture (experimental)

Independent of `SLACK_MODE=real` and of the Slack Browser Reader.

Setup: `windows-notification-listener/README.md`

Limitations:

- captures only notifications Windows actually receives
- muted chats may not appear
- DND may prevent or delay notifications
- notification text can be truncated
- historical Slack messages are unavailable
- outgoing messages are generally unavailable
- threads and conversation context are incomplete
- notification grouping can hide individual messages
- Slack Desktop source identification may vary by installation
