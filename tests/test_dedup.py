from jobfinder.dedup import dedup_key


def test_same_job_different_sites_same_key():
    assert dedup_key("Northwind Labs", "Senior Python Developer (Remote)") == \
           dedup_key("northwind labs", "Python Developer — remote")


def test_different_titles_differ():
    assert dedup_key("Acme", "Backend Developer") != dedup_key("Acme", "Frontend Developer")


def test_tech_names_not_collapsed():
    keys = {dedup_key("Acme", t) for t in ("C++ Developer", "C# Developer", "C Developer")}
    assert len(keys) == 3
    assert dedup_key("A", ".NET Developer") != dedup_key("A", "NET Developer")
    assert dedup_key("A", "Node.js Developer") != dedup_key("A", "Node Developer")


def test_full_stack_keeps_full_but_fulltime_dropped():
    assert "full" in dedup_key("Acme", "Full Stack Developer")
    assert dedup_key("Acme", "Python Developer Full-time") == dedup_key("Acme", "Python Developer")
    assert dedup_key("Acme", "Python Developer full time") == dedup_key("Acme", "Python Developer")
