using System.Diagnostics;

namespace TrafficManager.NotificationListener;

internal static class SafeLog
{
    public static void Info(string message)
    {
        Debug.WriteLine("[tma-listener] " + message);
        Trace.WriteLine("[tma-listener] " + message);
    }
}
