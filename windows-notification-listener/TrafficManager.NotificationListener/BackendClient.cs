using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace TrafficManager.NotificationListener;

internal sealed class BackendClient : IDisposable
{
    private const int MaxQueue = 50;
    private const int MaxBurst = 100;
    private static readonly TimeSpan ExpireAfter = TimeSpan.FromMinutes(10);
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNamingPolicy = null };

    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(8) };
    private readonly object _gate = new();
    private readonly List<QueuedEvent> _queue = [];
    private readonly HashSet<string> _seen = [];

    public string BackendUrl { get; set; } = "http://127.0.0.1:8000";
    public string Token { get; set; } = "";
    public bool LastBackendOk { get; private set; } = true;

    public bool TryEnqueue(SlackNotificationEvent payload)
    {
        lock (_gate)
        {
            if (!_seen.Add(payload.NotificationExternalId))
            {
                SafeLog.Info("event duplicate");
                return false;
            }

            if (_seen.Count > 500)
            {
                _seen.Clear();
                _seen.Add(payload.NotificationExternalId);
            }

            if (_queue.Count >= MaxBurst)
            {
                SafeLog.Info("event skipped reason=queue_full");
                return false;
            }

            _queue.Add(new QueuedEvent(payload, DateTimeOffset.UtcNow));
            if (_queue.Count > MaxQueue)
            {
                _queue.RemoveAt(0);
            }
        }

        return true;
    }

    public async Task FlushAsync(CancellationToken cancellationToken)
    {
        List<QueuedEvent> snapshot;
        lock (_gate)
        {
            var cutoff = DateTimeOffset.UtcNow - ExpireAfter;
            _queue.RemoveAll(item => item.EnqueuedAt < cutoff);
            snapshot = _queue.ToList();
        }

        foreach (var item in snapshot)
        {
            var ok = await PostAsync("/api/integrations/slack-notifications/events", item.Payload, cancellationToken).ConfigureAwait(false);
            if (!ok)
            {
                LastBackendOk = false;
                SafeLog.Info("backend unavailable");
                return;
            }

            lock (_gate)
            {
                _queue.RemoveAll(queued => queued.Payload.NotificationExternalId == item.Payload.NotificationExternalId);
            }

            LastBackendOk = true;
            SafeLog.Info("event delivered");
        }
    }

    public async Task<bool> HeartbeatAsync(HeartbeatPayload payload, CancellationToken cancellationToken)
    {
        var ok = await PostAsync("/api/integrations/slack-notifications/heartbeat", payload, cancellationToken).ConfigureAwait(false);
        LastBackendOk = ok;
        if (!ok)
        {
            SafeLog.Info("backend unavailable");
        }

        return ok;
    }

    private async Task<bool> PostAsync<T>(string path, T payload, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(Token))
        {
            return false;
        }

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, BackendUrl.TrimEnd('/') + path);
            request.Headers.TryAddWithoutValidation("X-TMA-Local-Token", Token);
            request.Content = JsonContent.Create(payload, options: JsonOptions);
            using var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false);
            return response.IsSuccessStatusCode;
        }
        catch (Exception)
        {
            return false;
        }
    }

    public void Dispose()
    {
        _http.Dispose();
    }

    private sealed record QueuedEvent(SlackNotificationEvent Payload, DateTimeOffset EnqueuedAt);
}
