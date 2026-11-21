from jobfinder.dedup import dedup_key


def test_same_job_different_sites_same_key():
    assert dedup_key("Northwind Labs", "Senior Python Developer (Remote)") == \
           dedup_key("northwind labs", "Python Developer — remote")


def test_different_titles_differ():
    assert dedup_key("Acme", "Backend Developer") != dedup_key("Acme", "Frontend Developer")
