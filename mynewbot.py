<script>
function setupCascade(stageId, termId, gradeId, subjectId) {
    const stageSelect = document.getElementById(stageId);
    const termSelect = document.getElementById(termId);
    const gradeSelect = document.getElementById(gradeId);
    const subjectSelect = document.getElementById(subjectId);

    function filterTerms() {
        const stageVal = stageSelect.value;
        termSelect.querySelectorAll('option[data-stage]').forEach(opt => {
            opt.style.display = (opt.dataset.stage === stageVal) ? '' : 'none';
        });
        if (termSelect.selectedOptions[0].style.display === 'none') termSelect.value = "";
    }

    function filterGrades() {
        const termVal = termSelect.value;
        gradeSelect.querySelectorAll('option[data-term]').forEach(opt => {
            opt.style.display = (opt.dataset.term === termVal) ? '' : 'none';
        });
        if (gradeSelect.selectedOptions[0].style.display === 'none') gradeSelect.value = "";
    }

    function filterSubjects() {
        const gradeVal = gradeSelect.value;
        subjectSelect.querySelectorAll('option[data-grade]').forEach(opt => {
            opt.style.display = (opt.dataset.grade === gradeVal) ? '' : 'none';
        });
        if (subjectSelect.selectedOptions[0].style.display === 'none') subjectSelect.value = "";
    }

    stageSelect.addEventListener('change', () => {
        filterTerms();
        filterGrades();
        filterSubjects();
    });

    termSelect.addEventListener('change', () => {
        filterGrades();
        filterSubjects();
    });

    gradeSelect.addEventListener('change', () => {
        filterSubjects();
    });

    filterTerms();
    filterGrades();
    filterSubjects();
}

document.addEventListener('DOMContentLoaded', function() {
    setupCascade('stage_select', 'term_select', 'grade_select', 'subject_select');
});
</script>
