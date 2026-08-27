import pytest
from fastapi.testclient import TestClient

from main import app
from storage import db
from storage.meeting_store import MeetingStore

client = TestClient(app)

def test_delete_meeting(isolated_storage):
    # Setup
    meeting_id = "test-delete-123"
    store = MeetingStore.create(meeting_id, "Test Deletion", "standard", {})
    
    # Verify creation
    assert store.meeting_dir.exists()
    
    # DB entry must exist for main.py to delete it
    row = store.to_summary_row()
    row["status"] = "completed"
    db.upsert_meeting(row)
    
    # Execute deletion
    resp = client.delete(f"/meetings/{meeting_id}")
    
    # Assert successful
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "meeting_id": meeting_id}
    
    # Assert directory and files are gone
    assert not store.meeting_dir.exists()
    
    # Assert DB is updated
    assert db.get_meeting(meeting_id) is None

def test_delete_active_meeting(isolated_storage):
    meeting_id = "test-active-123"
    store = MeetingStore.create(meeting_id, "Test Active", "standard", {})
    
    row = store.to_summary_row()
    row["status"] = "recording" # Active status
    db.upsert_meeting(row)
    
    resp = client.delete(f"/meetings/{meeting_id}")
    
    assert resp.status_code == 400
    assert "active meeting" in resp.json()["detail"]
    
    # Assert directory still exists
    assert store.meeting_dir.exists()
    # Assert DB still has it
    assert db.get_meeting(meeting_id) is not None

def test_delete_nonexistent_meeting(isolated_storage):
    resp = client.delete("/meetings/does-not-exist")
    assert resp.status_code == 404
