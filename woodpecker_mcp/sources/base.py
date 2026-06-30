"""Connector interfaces - the thin seam between the graph and where data comes
from. Implement these against your infra (Docker, Kubernetes, a CMDB, traces...)
and the graph/diagnosis logic is unchanged.
"""
from abc import ABC, abstractmethod


class TopologySource(ABC):
    """Discovers system structure: services, their containers/instances, and the
    dependency edges between services (who calls / relies on whom)."""

    @abstractmethod
    def discover(self):
        """Return (services, containers, dep_edges).

        services:   list of {name, role}
        containers: list of {name, service, state, health, restarts, image}
        dep_edges:  list of (src_service, dst_service)  # src depends on dst
        """
        raise NotImplementedError


class MetricsSource(ABC):
    """Live telemetry the graph needs - three signals, expressed by intent so
    each backend (Prometheus, Datadog, New Relic, CloudWatch...) translates them
    into its own query language. The graph/diagnosis logic stays backend-agnostic.
    """

    @abstractmethod
    def targets(self):
        """Return list of {job, service, health, endpoint} for active scrape
        targets. Drives blind-spot / monitoring-gap detection."""
        raise NotImplementedError

    @abstractmethod
    def error_rates(self):
        """Return {service: failed-requests-per-second}. Empty dict if the
        backend cannot report it. Drives the 'erroring' status that container
        health misses (a process up but returning 5xx)."""
        raise NotImplementedError

    def db_up(self):
        """Return True/False for database liveness, or None if the backend
        cannot report it (the default). A DB process can be down while its
        metrics exporter target is still up."""
        return None
