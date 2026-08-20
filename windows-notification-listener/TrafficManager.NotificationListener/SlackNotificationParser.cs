using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace TrafficManager.NotificationListener;

/// <summary>
/// Keep in sync with backend/app/integrations/slack_notification_parser.py
/// </summary>
internal static class SlackNotificationParser
{
    private static readonly Regex AggregateRe = new(
        @"^(?:\d+\s+new messages?|new activity(?: in slack)?|you have (?:unread |new )?messages?|unread messages?|new messages? in slack|slack$)\.?$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex ChannelPrefixRe = new(
        @"^(?:channel:\s*|#)(.+)$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex SenderBodyRe = new(
        @"^(.{1,80}?):\s+(.+)$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex ThreadHintRe = new(
        @"\breplied to a thread\b|\bin a thread\b",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex NonSlugRe = new(@"[^a-z0-9]+", RegexOptions.Compiled);

    public static ParseResult Parse(
        IReadOnlyList<string> textElements,
        AppIdentity identity,
        string? notificationId,
        string? createdAt,
        IEnumerable<string>? extraSourceIds = null,
        bool truncationFlagged = false)
    {
        var sourceKind = NotificationSourceClassifier.Classify(identity, extraSourceIds);
        var sourceId = NotificationSourceClassifier.SourceId(identity);
        var lines = Lines(textElements);
        var emptyId = MessageId(sourceId, notificationId, createdAt, null, "");
        if (sourceKind != NotificationSourceClassifier.SlackDesktop)
        {
            return Skip(sourceKind, sourceKind == NotificationSourceClassifier.Other ? "unrelated" : "browser_unknown", sourceId, emptyId);
        }

        if (lines.Count == 0)
        {
            return Skip(sourceKind, "empty", sourceId, emptyId);
        }

        if (lines.Any(IsAggregate) || IsAggregate(string.Join(" ", lines)))
        {
            return Skip(sourceKind, "aggregate", sourceId, emptyId);
        }

        var title = lines[0];
        var rest = lines.Skip(1).ToList();
        if (title.Equals("slack", StringComparison.OrdinalIgnoreCase) && rest.Count > 0)
        {
            title = rest[0];
            rest = rest.Skip(1).ToList();
            if (IsAggregate(title) || rest.Any(IsAggregate) || IsAggregate(string.Join(" ", new[] { title }.Concat(rest))))
            {
                return Skip(sourceKind, "aggregate", sourceId, emptyId);
            }
        }

        var conversationKind = "direct";
        string? conversationHint = null;
        string? senderName = null;
        var body = string.Join("\n", rest);
        var channelMatch = ChannelPrefixRe.Match(title);
        if (channelMatch.Success)
        {
            conversationKind = "channel";
            conversationHint = channelMatch.Groups[1].Value.Trim();
            var senderMatch = SenderBodyRe.Match(body);
            if (senderMatch.Success)
            {
                senderName = senderMatch.Groups[1].Value.Trim();
                body = senderMatch.Groups[2].Value.Trim();
            }
        }
        else if (rest.Count == 0 && SenderBodyRe.IsMatch(title))
        {
            var senderMatch = SenderBodyRe.Match(title);
            senderName = senderMatch.Groups[1].Value.Trim();
            body = senderMatch.Groups[2].Value.Trim();
            conversationHint = senderName;
        }
        else
        {
            senderName = title;
            conversationHint = title;
        }

        body = Normalize(body);
        if (string.IsNullOrWhiteSpace(body))
        {
            return Skip(sourceKind, "empty", sourceId, emptyId);
        }

        if (IsAggregate(body))
        {
            return Skip(sourceKind, "aggregate", sourceId, emptyId);
        }

        var hint = conversationHint ?? senderName ?? "unknown";
        var confidence = conversationKind == "channel" && !string.IsNullOrWhiteSpace(senderName)
            ? "high"
            : conversationKind == "direct" && !string.IsNullOrWhiteSpace(senderName)
                ? "medium"
                : "low";
        if (confidence == "low")
        {
            return Skip(sourceKind, "low_confidence", sourceId, emptyId);
        }

        var chatId = ChatId(conversationKind, hint);
        var messageId = MessageId(sourceId, notificationId, createdAt, senderName, body);
        return new ParseResult
        {
            SourceKind = sourceKind,
            SkipReason = null,
            SenderName = senderName,
            Text = body,
            ConversationHint = conversationHint,
            ConversationKind = conversationKind,
            MappingConfidence = confidence,
            IsTruncated = DetectTruncation(body, truncationFlagged),
            NotificationExternalId = messageId,
            ChatExternalId = chatId,
            ThreadHint = ThreadHintRe.IsMatch(string.Join("\n", lines)) ? "thread" : null,
            SourceId = sourceId,
        };
    }

    public static SlackNotificationEvent ToEvent(ParseResult parsed, string receivedAt)
    {
        return new SlackNotificationEvent
        {
            NotificationExternalId = parsed.NotificationExternalId,
            ReceivedAt = receivedAt,
            ConversationHint = parsed.ConversationHint,
            ConversationKind = parsed.ConversationKind,
            SenderName = parsed.SenderName,
            Text = parsed.Text ?? "",
            IsTruncated = parsed.IsTruncated,
            MappingConfidence = parsed.MappingConfidence,
            ThreadHint = parsed.ThreadHint,
            SourceId = parsed.SourceId,
        };
    }

    private static ParseResult Skip(string sourceKind, string reason, string sourceId, string emptyId)
    {
        return new ParseResult
        {
            SourceKind = sourceKind,
            SkipReason = reason,
            SourceId = sourceId,
            NotificationExternalId = emptyId,
        };
    }

    private static bool IsAggregate(string? value)
    {
        var text = Normalize(value);
        return text.Length > 0 && AggregateRe.IsMatch(text);
    }

    private static bool DetectTruncation(string text, bool flagged)
    {
        if (flagged)
        {
            return true;
        }

        var stripped = text.TrimEnd();
        return stripped.EndsWith("…", StringComparison.Ordinal) || stripped.EndsWith("...", StringComparison.Ordinal) || stripped.Length >= 220;
    }

    private static string ChatId(string kind, string hint)
    {
        var prefix = kind == "channel" ? "channel" : "dm";
        return $"notification:{prefix}:{Slug(hint)}";
    }

    private static string Slug(string value)
    {
        var lowered = Normalize(value).ToLowerInvariant().TrimStart('#');
        var slug = NonSlugRe.Replace(lowered, "-").Trim('-');
        if (slug.Length == 0)
        {
            slug = "unknown";
        }

        return slug.Length <= 80 ? slug : slug[..80];
    }

    private static string MessageId(string sourceId, string? notificationId, string? createdAt, string? sender, string text)
    {
        string material;
        if (!string.IsNullOrWhiteSpace(notificationId) && !string.IsNullOrWhiteSpace(sourceId))
        {
            material = $"{sourceId}\n{notificationId}\n{createdAt ?? ""}";
        }
        else
        {
            var bucket = (createdAt ?? "").Length >= 16 ? createdAt![..16] : createdAt ?? "";
            material = $"{sourceId}\n{sender ?? ""}\n{text}\n{bucket}";
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(material));
        var hex = Convert.ToHexString(hash).ToLowerInvariant()[..32];
        return "n_" + hex;
    }

    private static List<string> Lines(IEnumerable<string> textElements)
    {
        return textElements.Select(Normalize).Where(item => item.Length > 0).ToList();
    }

    private static string Normalize(string? value)
    {
        return Regex.Replace((value ?? "").Replace("\r\n", "\n"), "[ \t]+", " ").Trim();
    }
}
