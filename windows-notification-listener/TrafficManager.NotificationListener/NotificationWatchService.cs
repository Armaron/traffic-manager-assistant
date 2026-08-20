using Windows.UI.Notifications;
using Windows.UI.Notifications.Management;

namespace TrafficManager.NotificationListener;

internal sealed class NotificationWatchService : IDisposable
{
    private readonly BackendClient _backend;
    private readonly AppSettings _settings;
    private UserNotificationListener? _listener;
    private CancellationTokenSource? _cts;
    private Task? _heartbeat;

    public string Access { get; private set; } = "unspecified";
    public bool SlackSourceDetected { get; private set; }
    public DateTimeOffset? LastSlackAt { get; private set; }

    public event Action? StateChanged;
    public event Action<DiscoveryRow>? Discovered;
    public event Action<string>? DebugText;

    public NotificationWatchService(BackendClient backend, AppSettings settings)
    {
        _backend = backend;
        _settings = settings;
    }

    public async Task<string> RequestAccessAsync()
    {
        try
        {
            _listener ??= UserNotificationListener.Current;
            var status = await _listener.RequestAccessAsync();
            Access = MapAccess(status);
            SafeLog.Info("permission=" + Access);
            if (Access == "allowed")
            {
                Start();
            }

            StateChanged?.Invoke();
            return Access;
        }
        catch (Exception)
        {
            Access = "denied";
            StateChanged?.Invoke();
            return Access;
        }
    }

    public void RefreshAccess()
    {
        try
        {
            _listener ??= UserNotificationListener.Current;
            Access = MapAccess(_listener.GetAccessStatus());
            if (Access == "allowed")
            {
                Start();
            }
        }
        catch (Exception)
        {
            Access = "unspecified";
        }

        StateChanged?.Invoke();
    }

    private void Start()
    {
        if (_listener is null || _cts != null)
        {
            return;
        }

        _listener.NotificationChanged += OnNotificationChanged;
        _cts = new CancellationTokenSource();
        _heartbeat = Task.Run(() => HeartbeatLoop(_cts.Token));
        SafeLog.Info("listener started");
        _ = Task.Run(DiscoverCurrentAsync);
    }

    private async Task DiscoverCurrentAsync()
    {
        if (_listener is null || Access != "allowed")
        {
            return;
        }

        try
        {
            var notifications = await _listener.GetNotificationsAsync(NotificationKinds.Toast);
            foreach (var notification in notifications)
            {
                var identity = ReadIdentity(notification);
                var kind = NotificationSourceClassifier.Classify(identity, _settings.ExtraSourceIdList());
                if (kind == NotificationSourceClassifier.SlackDesktop)
                {
                    SlackSourceDetected = true;
                }

                if (_settings.DiscoveryMode)
                {
                    RaiseDiscovery(notification, identity, kind);
                }
            }

            StateChanged?.Invoke();
        }
        catch (Exception)
        {
            // Access revoked or API unavailable. Keep the helper running.
        }
    }

    private async void OnNotificationChanged(UserNotificationListener sender, UserNotificationChangedEventArgs args)
    {
        if (args.ChangeKind != UserNotificationChangedKind.Added)
        {
            return;
        }

        UserNotification? notification = null;
        try
        {
            notification = sender.GetNotification(args.UserNotificationId);
        }
        catch (Exception)
        {
            return;
        }

        if (notification is null)
        {
            return;
        }

        var identity = ReadIdentity(notification);
        var sourceKind = NotificationSourceClassifier.Classify(identity, _settings.ExtraSourceIdList());
        if (_settings.DiscoveryMode)
        {
            RaiseDiscovery(notification, identity, sourceKind);
        }

        if (sourceKind != NotificationSourceClassifier.SlackDesktop)
        {
            return;
        }

        SlackSourceDetected = true;
        var texts = ReadText(notification);
        var created = notification.CreationTime.ToUniversalTime().ToString("o");
        var parsed = SlackNotificationParser.Parse(
            texts,
            identity,
            notification.Id.ToString(),
            created,
            _settings.ExtraSourceIdList());
        if (parsed.SkipReason != null)
        {
            SafeLog.Info("event skipped reason=" + parsed.SkipReason);
            StateChanged?.Invoke();
            return;
        }

        SafeLog.Info("source=slack_desktop");
        SafeLog.Info("notification parsed");
        if (_settings.DebugMode)
        {
            DebugText?.Invoke(parsed.Text ?? "");
        }

        var payload = SlackNotificationParser.ToEvent(parsed, created);
        if (_backend.TryEnqueue(payload))
        {
            await _backend.FlushAsync(CancellationToken.None).ConfigureAwait(false);
            if (_backend.LastBackendOk)
            {
                LastSlackAt = DateTimeOffset.Now;
            }
        }

        StateChanged?.Invoke();
    }

    private async Task HeartbeatLoop(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await _backend.HeartbeatAsync(
                    new HeartbeatPayload
                    {
                        ListenerAccess = Access,
                        SlackSourceDetected = SlackSourceDetected,
                    },
                    cancellationToken).ConfigureAwait(false);
                await _backend.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (Exception)
            {
                SafeLog.Info("backend unavailable");
            }

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(20), cancellationToken).ConfigureAwait(false);
            }
            catch (TaskCanceledException)
            {
                break;
            }
        }
    }

    private void RaiseDiscovery(UserNotification notification, AppIdentity identity, string classified)
    {
        Discovered?.Invoke(new DiscoveryRow
        {
            DisplayName = identity.DisplayName ?? "",
            SourceId = NotificationSourceClassifier.SourceId(identity),
            Kind = "toast",
            TextElements = ReadText(notification).Count,
            ClassifiedAs = classified,
        });
    }

    private static AppIdentity ReadIdentity(UserNotification notification)
    {
        var identity = new AppIdentity();
        try
        {
            var info = notification.AppInfo;
            identity.DisplayName = info?.DisplayInfo?.DisplayName;
            identity.PackageFamilyName = info?.PackageFamilyName;
            identity.AppUserModelId = info?.AppUserModelId;
        }
        catch (Exception)
        {
            // Some toast sources omit AppInfo. Treat as unknown.
        }

        return identity;
    }

    private static List<string> ReadText(UserNotification notification)
    {
        try
        {
            var binding = notification.Notification.Visual.GetBinding(KnownNotificationBindings.ToastGeneric);
            var elements = binding?.GetTextElements();
            if (elements is null)
            {
                return [];
            }

            return elements.Select(item => item.Text ?? "").ToList();
        }
        catch (Exception)
        {
            return [];
        }
    }

    private static string MapAccess(UserNotificationListenerAccessStatus status)
    {
        return status switch
        {
            UserNotificationListenerAccessStatus.Allowed => "allowed",
            UserNotificationListenerAccessStatus.Denied => "denied",
            _ => "unspecified",
        };
    }

    public void Dispose()
    {
        if (_listener != null)
        {
            _listener.NotificationChanged -= OnNotificationChanged;
        }

        _cts?.Cancel();
        _cts?.Dispose();
    }
}
