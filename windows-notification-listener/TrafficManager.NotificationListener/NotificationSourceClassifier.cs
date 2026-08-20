namespace TrafficManager.NotificationListener;

internal static class NotificationSourceClassifier
{
    public const string SlackDesktop = "slack_desktop";
    public const string BrowserUnknown = "browser_unknown";
    public const string Other = "other";

    private static readonly string[] SlackFragments =
    [
        "com.tinyspeck.slackdesktop",
        "91750d7e.slack",
        "slack_8she8kybcnzg4",
        "slack.slack",
    ];

    private static readonly string[] BrowserFragments =
    [
        "google chrome",
        "chrome",
        "microsoft edge",
        "msedge",
        "firefox",
        "mozilla firefox",
        "brave",
        "opera",
        "chromium",
        "google.chrome",
        "microsoft.microsoftedge",
        "mozilla.firefox",
    ];

    public static string Classify(AppIdentity identity, IEnumerable<string>? extraSourceIds = null)
    {
        var blob = Blob(identity);
        var display = (identity.DisplayName ?? "").Trim().ToLowerInvariant();
        foreach (var extra in extraSourceIds ?? [])
        {
            var item = extra.Trim().ToLowerInvariant();
            if (item.Length > 0 && blob.Contains(item, StringComparison.Ordinal))
            {
                return SlackDesktop;
            }
        }

        foreach (var fragment in SlackFragments)
        {
            if (blob.Contains(fragment, StringComparison.Ordinal))
            {
                return SlackDesktop;
            }
        }

        foreach (var fragment in BrowserFragments)
        {
            if (blob.Contains(fragment, StringComparison.Ordinal))
            {
                return BrowserUnknown;
            }
        }

        return display == "slack" ? SlackDesktop : Other;
    }

    public static string SourceId(AppIdentity identity)
    {
        if (!string.IsNullOrWhiteSpace(identity.PackageFamilyName))
        {
            return identity.PackageFamilyName.Trim();
        }

        if (!string.IsNullOrWhiteSpace(identity.AppUserModelId))
        {
            return identity.AppUserModelId.Trim();
        }

        if (!string.IsNullOrWhiteSpace(identity.DisplayName))
        {
            return identity.DisplayName.Trim();
        }

        return "unknown";
    }

    private static string Blob(AppIdentity identity)
    {
        return string.Join(" ", identity.DisplayName, identity.PackageFamilyName, identity.AppUserModelId)
            .Trim()
            .ToLowerInvariant();
    }
}
