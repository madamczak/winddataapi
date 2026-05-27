import json
import os

def test_sample_dashboard_structure():
    """Test that the sample dashboard JSON has the expected structure."""
    dashboard_path = "sample_dashboard.json"
    assert os.path.exists(dashboard_path), f"Dashboard file {dashboard_path} not found"
    
    with open(dashboard_path, 'r') as f:
        dashboard = json.load(f)
    
    # Check required top-level keys
    assert "annotations" in dashboard
    assert "cursorSync" in dashboard
    assert "editable" in dashboard
    assert "elements" in dashboard
    assert "layout" in dashboard
    assert "links" in dashboard
    assert "liveNow" in dashboard
    assert "preload" in dashboard
    assert "schemaVersion" in dashboard
    assert "style" in dashboard
    assert "tags" in dashboard
    assert "templating" in dashboard
    assert "time" in dashboard
    assert "timepicker" in dashboard
    assert "title" in dashboard
    assert "uid" in dashboard
    assert "version" in dashboard
    assert "weekStart" in dashboard
    
    # Check specific values
    assert dashboard["title"] == "Sample Dashboard"
    assert dashboard["uid"] == "sample-dashboard"
    assert dashboard["version"] == 1
    assert dashboard["schemaVersion"] == 38
    assert dashboard["editable"] is True
    assert dashboard["liveNow"] is False
    assert dashboard["preload"] is False
    
    # Check time structure
    assert "from" in dashboard["time"]
    assert "to" in dashboard["time"]
    assert dashboard["time"]["from"] == "now-6h"
    assert dashboard["time"]["to"] == "now"
    
    # Check timepicker structure
    assert "refresh_intervals" in dashboard["timepicker"]
    assert "time_options" in dashboard["timepicker"]
    assert isinstance(dashboard["timepicker"]["refresh_intervals"], list)
    assert isinstance(dashboard["timepicker"]["time_options"], list)
    
    # Check layout
    assert dashboard["layout"]["type"] == "grid"
    
    # Check annotations list
    assert isinstance(dashboard["annotations"]["list"], list)
    
    # Check templating list
    assert isinstance(dashboard["templating"]["list"], list)
    
    # Check tags list
    assert isinstance(dashboard["tags"], list)
    
    print("All tests passed!")

if __name__ == "__main__":
    test_sample_dashboard_structure()