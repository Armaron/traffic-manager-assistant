using System.IO;

namespace TrafficManager.NotificationListener;

internal sealed class AppSettings
{
    public string BackendUrl { get; set; } = "http://127.0.0.1:8000";
    public string LocalToken { get; set; } = "";
    public string ExtraSourceIds { get; set; } = "";
    public bool DiscoveryMode { get; set; }
    public bool DebugMode { get; set; }

    public IEnumerable<string> ExtraSourceIdList()
    {
        return ExtraSourceIds.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
    }

    public static AppSettings Load()
    {
        var settings = new AppSettings();
        var envUrl = Environment.GetEnvironmentVariable("TMA_BACKEND_URL");
        if (!string.IsNullOrWhiteSpace(envUrl))
        {
            settings.BackendUrl = envUrl.Trim().TrimEnd('/');
        }

        var envToken = Environment.GetEnvironmentVariable("SLACK_NOTIFICATION_LOCAL_TOKEN");
        if (!string.IsNullOrWhiteSpace(envToken))
        {
            settings.LocalToken = envToken.Trim();
        }

        var extra = Environment.GetEnvironmentVariable("SLACK_NOTIFICATION_SOURCE_IDS");
        if (!string.IsNullOrWhiteSpace(extra))
        {
            settings.ExtraSourceIds = extra.Trim();
        }

        if (string.IsNullOrWhiteSpace(settings.LocalToken))
        {
            foreach (var candidate in TokenCandidates())
            {
                if (File.Exists(candidate))
                {
                    var stored = File.ReadAllText(candidate).Trim();
                    if (stored.Length > 0)
                    {
                        settings.LocalToken = stored;
                        break;
                    }
                }
            }
        }

        return settings;
    }

    private static IEnumerable<string> TokenCandidates()
    {
        var start = AppContext.BaseDirectory;
        yield return Path.Combine(start, "slack_notification_token");
        var dir = new DirectoryInfo(start);
        for (var i = 0; i < 6 && dir != null; i++)
        {
            yield return Path.Combine(dir.FullName, "data", "slack_notification_token");
            dir = dir.Parent;
        }
    }
}
