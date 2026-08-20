using System.Text.Json.Serialization;

namespace TrafficManager.NotificationListener;

internal sealed class SlackNotificationEvent
{
    [JsonPropertyName("source")]
    public string Source { get; set; } = "slack_notification";

    [JsonPropertyName("notification_external_id")]
    public string NotificationExternalId { get; set; } = "";

    [JsonPropertyName("received_at")]
    public string ReceivedAt { get; set; } = "";

    [JsonPropertyName("conversation_hint")]
    public string? ConversationHint { get; set; }

    [JsonPropertyName("conversation_kind")]
    public string ConversationKind { get; set; } = "direct";

    [JsonPropertyName("sender_name")]
    public string? SenderName { get; set; }

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";

    [JsonPropertyName("is_truncated")]
    public bool IsTruncated { get; set; }

    [JsonPropertyName("mapping_confidence")]
    public string MappingConfidence { get; set; } = "medium";

    [JsonPropertyName("thread_hint")]
    public string? ThreadHint { get; set; }

    [JsonPropertyName("source_id")]
    public string? SourceId { get; set; }
}

internal sealed class HeartbeatPayload
{
    [JsonPropertyName("listener_access")]
    public string ListenerAccess { get; set; } = "unspecified";

    [JsonPropertyName("slack_source_detected")]
    public bool SlackSourceDetected { get; set; }
}

internal sealed class ParseResult
{
    public string SourceKind { get; set; } = NotificationSourceClassifier.Other;
    public string? SkipReason { get; set; }
    public string? SenderName { get; set; }
    public string? Text { get; set; }
    public string? ConversationHint { get; set; }
    public string ConversationKind { get; set; } = "direct";
    public string MappingConfidence { get; set; } = "low";
    public bool IsTruncated { get; set; }
    public string NotificationExternalId { get; set; } = "";
    public string? ChatExternalId { get; set; }
    public string? ThreadHint { get; set; }
    public string SourceId { get; set; } = "unknown";
}

internal sealed class AppIdentity
{
    public string? DisplayName { get; set; }
    public string? PackageFamilyName { get; set; }
    public string? AppUserModelId { get; set; }
}

internal sealed class DiscoveryRow
{
    public string DisplayName { get; set; } = "";
    public string SourceId { get; set; } = "";
    public string Kind { get; set; } = "";
    public int TextElements { get; set; }
    public string ClassifiedAs { get; set; } = "";
}
