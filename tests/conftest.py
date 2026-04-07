import os

# Exclude tests/azureMonitor from collection — these tests require
# azure-monitor-opentelemetry and related packages that are not
# installed as part of the base test dependencies.
collect_ignore = [os.path.join(os.path.dirname(__file__), "azureMonitor")]
