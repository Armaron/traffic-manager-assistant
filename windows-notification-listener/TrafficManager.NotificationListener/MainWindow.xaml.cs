using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace TrafficManager.NotificationListener;

public partial class MainWindow : Window
{
    private readonly AppSettings _settings;
    private readonly BackendClient _backend;
    private readonly NotificationWatchService _watch;
    private bool _permissionPrompted;

    public MainWindow()
    {
        InitializeComponent();
        _settings = AppSettings.Load();
        _backend = new BackendClient
        {
            BackendUrl = _settings.BackendUrl,
            Token = _settings.LocalToken,
        };
        _watch = new NotificationWatchService(_backend, _settings);
        _watch.StateChanged += () => Dispatcher.Invoke(RenderState);
        _watch.Discovered += row => Dispatcher.Invoke(() => AddDiscovery(row));
        _watch.DebugText += text => Dispatcher.Invoke(() =>
        {
            DebugLabel.Text = text;
            DebugLabel.Visibility = _settings.DebugMode ? Visibility.Visible : Visibility.Collapsed;
        });
        TokenBox.Password = _settings.LocalToken;
        BackendUrlBox.Text = _settings.BackendUrl;
        SourceIdsBox.Text = _settings.ExtraSourceIds;
        SourceIdsBox.Tag = "SLACK_NOTIFICATION_SOURCE_IDS";
        if (string.IsNullOrWhiteSpace(SourceIdsBox.Text))
        {
            SourceIdsBox.Text = "";
        }

        Loaded += (_, _) =>
        {
            _watch.RefreshAccess();
            RenderState();
        };
        Closed += (_, _) =>
        {
            _watch.Dispose();
            _backend.Dispose();
        };
    }

    private async void AllowButton_Click(object sender, RoutedEventArgs e)
    {
        if (_permissionPrompted && _watch.Access == "denied")
        {
            DeniedHint.Visibility = Visibility.Visible;
            return;
        }

        _permissionPrompted = true;
        AllowButton.IsEnabled = false;
        await _watch.RequestAccessAsync();
        AllowButton.IsEnabled = true;
        RenderState();
    }

    private void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        _settings.BackendUrl = BackendUrlBox.Text.Trim().TrimEnd('/');
        _settings.LocalToken = TokenBox.Password.Trim();
        _settings.ExtraSourceIds = SourceIdsBox.Text.Trim();
        _backend.BackendUrl = _settings.BackendUrl;
        _backend.Token = _settings.LocalToken;
        RenderState();
    }

    private void FlagChanged(object sender, RoutedEventArgs e)
    {
        _settings.DiscoveryMode = DiscoveryBox.IsChecked == true;
        _settings.DebugMode = DebugBox.IsChecked == true;
        DebugLabel.Visibility = _settings.DebugMode ? Visibility.Visible : Visibility.Collapsed;
    }

    private void RenderState()
    {
        var access = _watch.Access;
        AccessLabel.Text = access == "allowed" ? "● Allowed" : access == "denied" ? "○ Denied" : "○ Not allowed";
        DeniedHint.Visibility = access == "denied" ? Visibility.Visible : Visibility.Collapsed;
        if (access == "allowed")
        {
            SlackLabel.Text = _watch.SlackSourceDetected ? "● Slack Desktop detected" : "○ Waiting";
        }
        else
        {
            SlackLabel.Text = "○ Waiting";
        }

        var backendOk = _backend.LastBackendOk;
        BackendLabel.Text = (backendOk ? "● " : "○ ") + _settings.BackendUrl;
        BackendLabel.Foreground = backendOk ? Brushes.LightGreen : Brushes.IndianRed;
        LastLabel.Text = _watch.LastSlackAt is DateTimeOffset moment ? moment.ToLocalTime().ToString("HH:mm") : "—";
    }

    private void AddDiscovery(DiscoveryRow row)
    {
        if (DiscoveryList.Items.Count > 20)
        {
            DiscoveryList.Items.RemoveAt(0);
        }

        DiscoveryList.Items.Add(
            $"{row.DisplayName} · {row.SourceId} · {row.Kind} · texts={row.TextElements} · {row.ClassifiedAs}");
    }
}
