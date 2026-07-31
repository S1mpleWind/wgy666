"""GitHub Webhook event handling.

Receives and processes GitHub webhook events (issue opened, etc.),
classifies them using the rule-based IssueClassifier, and stores
event records for later retrieval.
"""
