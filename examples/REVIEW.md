# Small reference exercise

These expected shapes were written during implementation, before any live model run. They are starting references for a human to review, not human-approved gold labels or measured results.

| Manufacturing class | Parent | HR class | Parent |
| --- | --- | --- | --- |
| QualityInspector | Agent | Recruiter | Agent |
| EquipmentInspection | Action | CandidateScreening | Action |
| InspectionReport | InformationObject | ScreeningReport | InformationObject |
| Equipment | PhysicalObject | JobDescription | InformationObject |
| InspectionChecklist | InformationObject | CandidateApplication | InformationObject |

Expected manufacturing associations:

```text
QualityInspector performs EquipmentInspection
EquipmentInspection produces InspectionReport
EquipmentInspection dependsOn Equipment
EquipmentInspection acceptsParam InspectionChecklist
```

Expected HR associations:

```text
Recruiter performs CandidateScreening
CandidateScreening produces ScreeningReport
CandidateScreening dependsOn JobDescription
CandidateScreening acceptsParam CandidateApplication
```

`manufacturing_02.txt` repeats the inspector and inspection concepts. It should reuse existing definitions. “Work near” should have no mapped predicate. Preserve that phrase as a skipped decision in the log rather than forcing it into `dependsOn`.

Names may differ while meanings agree. Conversely, mapping every candidate to a broad foundation class would lose useful distinctions. Check each proposed meaning and every parent.

For each domain, record expected classes recovered, missing or duplicated concepts, wrong parents, wrong relationships, and skipped concepts that should have been retained. Answer these questions from the output graph:

1. Which agent type performs the main action?
2. Which report type can that action produce?

Time the human reference creation, review, and corrections separately. Count class creation, deletion, reparenting, and relationship corrections. Use `review_template.json`; unmeasured fields stay `null`. Keep the raw graph and a separate corrected graph. These tiny exercises test the workflow; they cannot establish general time savings or agent reliability benefits.
