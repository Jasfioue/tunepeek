using System.Collections.Generic;
using System.Linq;

static class Picker
{
    /// players: (id, status) -> id для показа. Играющий важнее паузы, прежний — при равенстве.
    public static string Pick(IList<(string id, string status)> players, string prev) =>
        players.OrderBy(p => p.status == "Playing" ? 0 : p.status == "Paused" ? 1 : 2)
               .ThenBy(p => p.id == prev ? 0 : 1)
               .Select(p => p.id).FirstOrDefault();
}
