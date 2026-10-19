"""Table des routes du serveur unique.

Une route = un chemin exact et une fonction `(c, p, d) -> dict`. La construction
se fait a partir du module hote (MissionControl), qui fournit les fonctions :
aucun import circulaire, aucun etat cache.
"""

# Routes qui ne demandent pas de projet valide dans la requete.
SANS_PROJET = frozenset(('/api/mc/shutdown', '/api/mc/backups', '/api/mc/security/revoke'))


def construire(m):
    """Construit la table des routes pour le module hote `m`."""
    return {
        '/api/mc/security/token': lambda c, p, d: _jeton_agent(m, c, p, d),
        '/api/mc/security/revoke': lambda c, p, d: {'revoked': bool(m.mc_security.revoke(m.required_text(d, 'grant_id', 100)))},
        '/api/mc/documents/save': lambda c, p, d: m.mc_documents.save(c, p, d),
        '/api/mc/documents/delete': lambda c, p, d: m.mc_documents.delete(c, p, d),
        '/api/mc/documents/import': lambda c, p, d: _import_document(m, c, p, d),
        '/api/mc/agent': lambda c, p, d: m.agent_creer(c, p, d),
        '/api/mc/agent/update': lambda c, p, d: m.agent_modifier(c, p, d),
        '/api/mc/link': lambda c, p, d: m.mc_missions.lien_creer(c, p, d),
        '/api/mc/mission': lambda c, p, d: m.mc_missions.mission_creer(c, p, d),
        '/api/mc/assignment': lambda c, p, d: m.mc_missions.affectation_creer(c, p, d),
        '/api/mc/assignment/update': lambda c, p, d: m.mc_missions.affectation_modifier(c, p, d),
        '/api/mc/note': lambda c, p, d: m.mc_missions.note_creer(c, p, d),
        '/api/mc/decision': lambda c, p, d: m.mc_missions.decision_creer(c, p, d),
        '/api/mc/message': lambda c, p, d: m.mc_missions.message_envoyer(c, p, d),
        '/api/mc/message/read': lambda c, p, d: m.mc_missions.message_lire(c, p, d),
        '/api/mc/handoff/ack': lambda c, p, d: m.mc_missions.handoff_ack(c, p, d),
        '/api/mc/job': lambda c, p, d: m.job_creer(c, p, d),
        '/api/mc/job/run': lambda c, p, d: m.job_lancer(c, p, int(d['id'])),
        '/api/mc/job/pause': lambda c, p, d: m.job_pause(c, p, int(d['id'])),
        '/api/mc/job/resume': lambda c, p, d: m.job_reprendre(c, p, int(d['id'])),
        '/api/mc/job/approve': lambda c, p, d: m.job_approuver(c, p, int(d['id']), d),
        '/api/mc/job/reject': lambda c, p, d: m.job_refuser(c, p, int(d['id']), d),
        '/api/mc/job/cancel': lambda c, p, d: m.job_annuler(c, p, int(d['id'])),
        '/api/mc/job/test': lambda c, p, d: m.job_tester(c, p, int(d['id']), d),
        '/api/mc/job/validate': lambda c, p, d: m.job_valider(c, p, d),
        '/api/mc/job/commit': lambda c, p, d: m.job_commit(c, p, d),
        '/api/mc/review': lambda c, p, d: m.review_creer(c, p, d),
        '/api/mc/role': lambda c, p, d: m.role_creer(c, p, d),
        '/api/mc/branch': lambda c, p, d: m.branche_creer(c, p, d),
        '/api/mc/branch/update': lambda c, p, d: m.branche_modifier(c, p, d),
        '/api/mc/agent/clone': lambda c, p, d: m.agent_clone(c, p, d),
        '/api/mc/agent/archive': lambda c, p, d: m.agent_archiver(c, p, d),
        '/api/mc/recruit': lambda c, p, d: m.recrue_creer(c, p, d),
        '/api/mc/recruit/decide': lambda c, p, d: m.recrue_decider(c, p, d),
        '/api/mc/permissions': lambda c, p, d: m.permissions_definir(c, p, d),
        '/api/mc/settings': lambda c, p, d: m.reglage_definir(c, p, d),
        '/api/mc/backup': lambda c, p, d: {'file': m.sauvegarder().name},
        '/api/mc/restore': lambda c, p, d: m.restaurer_sauvegarde(c, p, d),
        '/api/mc/shutdown': lambda c, p, d: m.demander_arret(),
        '/api/mc/plan': lambda c, p, d: m.plan_proposer(c, p, d),
        '/api/mc/plan/apply': lambda c, p, d: m.plan_appliquer(c, p, d),
        '/api/mc/orchestrator/run': lambda c, p, d: m.orchestrateur_lancer(c, p, d),
        '/api/mc/charge': lambda c, p, d: m.charge_agents(c, p),
        '/api/mc/corbeille/purge': lambda c, p, d: m.purger_corbeille(c, p, d),
    }


def _jeton_agent(m, c, p, d):
    agent = m.agent(c, p, int(d['agent_id']))
    if agent['status'] == 'archived':
        raise ValueError('Agent archivé')
    return m.mc_security.issue(p, agent['id'], d.get('actions'), int(d.get('ttl', 900)))


def _import_document(m, c, p, d):
    resultat = m.mc_documents.import_file(c, p, d, m.reglages(c, p).get('workspace_dir'))
    m.audit(c, p, 'document_imported',
            {'id': resultat['item']['id'], 'filename': resultat['item']['title'], 'bytes': resultat['bytes']})
    return resultat
