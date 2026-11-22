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


from jobfinder.dedup import compatible


def test_different_levels_not_compatible():
    assert not compatible("Middle Python Developer (Django)", "Senior Python Developer")
    assert not compatible("Middle+ Python Developer", "Senior Python Developer")


def test_level_on_one_side_only_is_compatible():
    assert compatible("Senior Python Developer (Remote)", "Python Developer — remote")
    assert compatible("System Analyst (Senior)", "Senior System Analyst")


def test_different_bracket_qualifiers_not_compatible():
    assert not compatible("Data Scientist (RAG-платформа)", "Data Scientist (Внутренние сервисы)")
    assert not compatible("Старший разработчик Java (AI поисковый ассистент)",
                          "Старший разработчик Java (Платформа стриминговой обработки)")


def test_bracket_on_one_side_or_noise_brackets_compatible():
    assert compatible("C++ Engineer", "C++ Engineer (HFT)")
    assert compatible("Python Developer (Remote, Full-time)", "Python Developer")
    # Latin «c» and Cyrillic «с» look the same
    assert compatible("Python-разработчик (c желанием развиваться в Go)",
                      "Python-разработчик (с желанием развиваться в Go)")
