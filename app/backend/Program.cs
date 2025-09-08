using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var builder = WebApplication.CreateBuilder(args);

// CORS: allow local dev frontend
const string CorsPolicy = "AllowLocal";
builder.Services.AddCors(options =>
{
    options.AddPolicy(CorsPolicy, policy =>
        policy
            .AllowAnyOrigin()
            .AllowAnyHeader()
            .AllowAnyMethod());
});

builder.Services.AddEndpointsApiExplorer();

var app = builder.Build();

app.UseCors(CorsPolicy);

// Health endpoint
app.MapGet("/api/health", () => Results.Ok(new
{
    status = "ok",
    time = DateTimeOffset.UtcNow
}));

// Placeholder NL endpoint: returns empty plan; echoes input
app.MapPost("/api/nl", async (HttpRequest req) =>
{
    using var reader = new StreamReader(req.Body);
    var body = await reader.ReadToEndAsync();
    // In future, parse body and call AI or rules engine.
    return Results.Ok(new
    {
        steps = Array.Empty<object>(),
        explanation = "NL endpoint placeholder. No steps generated.",
        echo = body
    });
});

// Bind to a stable dev port for Vite proxy
app.Urls.Add("http://localhost:5199");

app.Run();
