"""Declaration des actions protegees.

Chaque fonction du serveur qui sert une action sensible porte son exigence :
`@action('approve', job_arg=True, payload_arg=1)`. L'ancien mecanisme rebindait
les fonctions dans `globals()` apres inspection de leur signature ; celui-ci est
explicite et se lit a la definition.
"""
import functools
import inspect

import mc_security


def action(nom, job_arg=False, payload_arg=None):
    """Marque une fonction comme servant l'action protegee `nom`."""
    def enveloppe(fonction):
        signature = inspect.signature(fonction)
        noms = list(signature.parameters)[2:]

        @functools.wraps(fonction)
        def garde(c, p, *args, **kwargs):
            lies = signature.bind(c, p, *args, **kwargs)
            lies.apply_defaults()
            donnees = lies.arguments.get(noms[payload_arg], {}) if payload_arg is not None else {}
            donnees = donnees or {}
            travail = lies.arguments.get(noms[0]) if job_arg else None
            if nom in ('validate', 'commit', 'review'):
                travail = donnees.get('job_id') or donnees.get('id')
            mc_security.require(c, p, nom, donnees, travail)
            return fonction(c, p, *args, **kwargs)

        garde.action_mc = nom
        return garde
    return enveloppe
