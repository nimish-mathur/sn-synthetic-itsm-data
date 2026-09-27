"""Name pools per country. Common first and last names, combined at random.
Any resemblance of a generated combination to a real person is coincidental."""
from __future__ import annotations

NAME_POOLS: dict[str, dict[str, list[str]]] = {
    "FR": {
        "first": ["Camille", "Louis", "Chloé", "Hugo", "Léa", "Lucas", "Manon", "Nathan", "Inès",
                  "Julien", "Sarah", "Antoine", "Emma", "Thomas", "Pauline", "Maxime", "Claire", "Romain"],
        "last": ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand", "Leroy",
                 "Moreau", "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux"],
    },
    "DE": {
        "first": ["Lukas", "Anna", "Felix", "Lea", "Jonas", "Hannah", "Paul", "Laura", "Leon",
                  "Sophie", "Tim", "Julia", "Jan", "Lena", "Niklas", "Marie", "Moritz", "Katharina"],
        "last": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
                 "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Braun", "Zimmermann"],
    },
    "IT": {
        "first": ["Luca", "Giulia", "Marco", "Chiara", "Matteo", "Francesca", "Alessandro", "Sara", "Andrea",
                  "Martina", "Davide", "Elena", "Simone", "Valentina", "Federico", "Alessia", "Stefano", "Silvia"],
        "last": ["Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci", "Marino",
                 "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa", "Giordano", "Mancini", "Rizzo"],
    },
    "PL": {
        "first": ["Jakub", "Anna", "Piotr", "Katarzyna", "Tomasz", "Magdalena", "Michał", "Agnieszka", "Paweł",
                  "Joanna", "Krzysztof", "Ewa", "Marcin", "Monika", "Łukasz", "Aleksandra", "Adam", "Natalia"],
        "last": ["Nowak", "Kowalski", "Wiśniewski", "Wójcik", "Kowalczyk", "Kamiński", "Lewandowski", "Zieliński",
                 "Szymański", "Woźniak", "Dąbrowski", "Kozłowski", "Jankowski", "Mazur", "Kwiatkowski",
                 "Krawczyk", "Piotrowski", "Grabowski"],
    },
    "NL": {
        "first": ["Daan", "Emma", "Sem", "Julia", "Lucas", "Sophie", "Milan", "Tess", "Levi",
                  "Anna", "Thijs", "Lotte", "Ruben", "Fleur", "Bram", "Sanne", "Jesse", "Eva"],
        "last": ["de Jong", "Jansen", "de Vries", "van den Berg", "van Dijk", "Bakker", "Janssen", "Visser",
                 "Smit", "Meijer", "de Boer", "Mulder", "de Groot", "Bos", "Vos", "Peters", "Hendriks", "Dekker"],
    },
    "ES": {
        "first": ["Hugo", "Lucía", "Martín", "María", "Pablo", "Paula", "Daniel", "Carmen", "Alejandro",
                  "Laura", "Javier", "Marta", "Diego", "Elena", "Adrián", "Sofía", "Álvaro", "Irene"],
        "last": ["García", "Rodríguez", "González", "Fernández", "López", "Martínez", "Sánchez", "Pérez",
                 "Gómez", "Martín", "Jiménez", "Ruiz", "Hernández", "Díaz", "Moreno", "Muñoz", "Álvarez", "Romero"],
    },
}
