---
document_id: pm-2026-07
document_type: postmortem
title: Post-Mortem Incident INC-2026-07 CoreDNS Conntrack Table Exhaustion
service: platform-dns
environment: production
severity: high
version: 1
---
# Post-Mortem: CoreDNS Conntrack Table Exhaustion

## Date
2026-03-29

## Impact
Random intermittent DNS resolution failures across all microservices.

## Root Cause
Linux kernel connection tracking (`nf_conntrack`) table filled up due to high rate of short-lived UDP DNS queries without NodeLocal DNSCache enabled.

## Resolution
Deployed NodeLocal DNSCache DaemonSet and increased `sysctl net.netfilter.nf_conntrack_max`.\n