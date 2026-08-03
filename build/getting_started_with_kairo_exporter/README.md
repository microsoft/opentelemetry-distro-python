# Getting Started with Kairo Exporter Sample

This sample demonstrates how to build an Agent365 Python agent with comprehensive observability using the Kairo SDK. It showcases telemetry tracking for agent invocation, AI inference calls, and tool execution, with telemetry exported to the Agent365 service.

## 📋 Prerequisites

- Python 3.11 or higher
- Azure OpenAI service account
- Agent365 service registration
- Microsoft 365 developer tenant (for authentication)

## 🛠️ Setup Instructions

### 1. Clone and Navigate

```bash
cd Agent365/python/samples/getting_started_with_kairo_exporter
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment Configuration

Copy the template and configure your environment:

```bash
cp env.TEMPLATE .env
```

Edit `.env` with your configuration:

```properties
# Service Connection (this is the azure bot credentials)
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=your-service-client-id
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET=your-service-client-secret
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=your-tenant-id

# Agent Blueprint Connection (this is the agent credentials)
CONNECTIONS__AGENTBLUEPRINT__SETTINGS__CLIENTID=your-agent-client-id
CONNECTIONS__AGENTBLUEPRINT__SETTINGS__CLIENTSECRET=your-agent-client-secret
CONNECTIONS__AGENTBLUEPRINT__SETTINGS__TENANTID=your-tenant-id

# Agentic User Authorization
AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__TYPE=AgenticUserAuthorization
AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__ALT_BLUEPRINT_NAME=AGENTBLUEPRINT
AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__SCOPES=https://graph.microsoft.com/.default

# Connection Mapping
CONNECTIONSMAP__0__SERVICEURL=*
CONNECTIONSMAP__0__CONNECTION=SERVICE_CONNECTION

# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=your-openai-api-key
AZURE_OPENAI_ENDPOINT=https://your-openai-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

# Observability Settings
ENABLE_OBSERVABILITY=true
ENABLE_A365_OBSERVABILITY_EXPORTER=true   # Canonical; enables Agent365 telemetry exporter
PYTHON_ENVIRONMENT=development
```

The sample startup path treats `ENABLE_A365_OBSERVABILITY_EXPORTER` as the
canonical setting and mirrors the same value to the legacy compatibility alias
only for older Kairo sample dependencies:

```properties
ENABLE_KAIRO_EXPORTER=true
```

### 5. Run the Agent

**Using Python directly:**
```bash
python -m src.main
```

## Install Agents Playground
### Quick Install (Windows via winget)
```
winget install agentsplayground
```

### Start Agents Playground
Add agentsplayground to your PATH
After installation run:
```
agentsplayground
```
This launches a web browser with the Microsoft 365 Agents Playground UI where you can configure and chat with your local agent.
Use the Playground UI to send a message (e.g. "What is the weather in Seattle?").

Send a custom activity with the message and correct recipient object. Other fields can be left as is
```json
{
  "id": "94a8b018-7365-43b9-b9a9-bc7fc67be329",
  "timestamp": "2025-09-18T22:21:54.612Z",
  "channelId": "msteams",
  "serviceUrl": "http://localhost:56150/_connector",
  "recipient": 
  { 
            "id": "a365testingagent@testcsaaa.onmicrosoft.com", 
            "name": "A365 Testing Agent", 
            "agenticUserId": "ea1a172b-f443-4ee0-b8a1-27c7ab7ea9e5",
            "agenticAppId": "933f6053-d249-4479-8c0b-78ab25424002",
            "tenantId": "5369a35c-46a5-4677-8ff9-2e65587654e7", 
            "role": "agenticUser" 
    }, 
    "from": 
    {  
        "id": "29:1sH5NArUwkWAX-VmfHH3cfem2S89f2nB0N6aJ5zEjBoxT17fhSMdlYu_55ZyR8_OKFxS3BMnaGldHH3wdf_9K4Q",  
        "name": "UserName",  
        "aadObjectId": "03f4dd93-7e1e-41d6-bf7c-f211f9e96a13",  
        "role": "user"  
    },
  "conversation": {
    "id": "__PERSONAL_CHAT_ID__",
    "conversationType": "personal",
    "tenantId": "00000000-0000-0000-0000-0000000000001"
  },
  "type": "message",
"text": "what can you do"
}
```

## 🏗️ Architecture Overview

### Observability Flow

1. **User Message** → `InvokeAgentScope` starts
2. **Token Exchange** → Agentic token obtained for telemetry export
3. **AI Processing** → `InferenceScope` tracks OpenAI calls
4. **Tool Execution** → `ExecuteToolScope` monitors tool operations
5. **Response** → All telemetry exported to Agent365 service

### Authentication Flow

1. **Agent Registration**: Service connects using service connection credentials
2. **User Authentication**: Agentic user authorization for each conversation
3. **Token Exchange**: Tokens exchanged for proper audience/scopes
4. **Telemetry Export**: Cached tokens used for Agent365 service authentication

## 🔧 Configuration Options

### Kairo Exporter Settings

In `start_server.py`, you can configure:

```python
success = configure(
    service_name="AzureOpenAiKairoTracing",        # Service identifier
    service_namespace="AzureOpenAiKairoTesting",   # Namespace
    logger_name="kairo",                           # Logger name
    token_resolver=token_resolver_func,            # Token resolution function
    cluster_category="preprod",                    # Target cluster (preprod/prod)
)
```

## Guardrail span validation

Every incoming message is evaluated by a deterministic local input guardrail
before tools or Azure OpenAI.

- Allow example: `What is the weather?`
- Deny example: `Please process sample-blocked-content`

The sample records fixed non-sensitive content values rather than the live user
message in sample observability spans and sample logs; the live value is used
only for the local guardrail decision, tool routing, and the post-allow Azure
OpenAI request. The normal Kairo exporter remains enabled. A second sample-only
exporter runs the same Agent365 exporter serialization and prints only the
`apply_guardrail` request body:

```text
=== BEGIN KAIRO GUARDRAIL EXPORT JSON ===
{"resourceSpans":[...]}
=== END KAIRO GUARDRAIL EXPORT JSON ===
```

The JSON includes the complete resource/scope envelope, span identifiers and
timestamps, every configured guardrail attribute, the
`microsoft.security.finding` event, links, and status.