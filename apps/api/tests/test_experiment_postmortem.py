from app.experiments import transition
from app.models import Experiment, Postmortem


def test_terminal_transition_writes_one_truthful_postmortem(db):
    experiment = Experiment(title="bounded fixture", hypothesis="stop cleanly", status="DRAFT")
    db.add(experiment)
    db.flush()

    transition(db, experiment, "TERMINATED")

    postmortem = db.query(Postmortem).filter_by(experiment_id=experiment.id).one()
    assert postmortem.repeat_decision == "do_not_repeat"
    assert postmortem.profit_loss_cents == 0
