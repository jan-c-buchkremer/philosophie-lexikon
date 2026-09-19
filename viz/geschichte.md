---
title: Analyse und Visualisierung des Atlas der Enzyklopädie Philosophie und Wissenschaftstheorie
description: Was 59.942 Querverweise der Enzyklopädie Philosophie und Wissenschaftstheorie über die Philosophie verraten.
---

<!--
Der Text des Essays. Gebaut mit:  uv run python scripts/build_story_html.py
(schreibt viz/geschichte.html; die HTML-Datei nicht von Hand ändern).

Konventionen über CommonMark hinaus:
  {key}                Zahl oder Name aus story.json, wird beim Laden eingesetzt.
                       Die Schlüssel stehen in viz/js/story-main.js, derive().
                       Kursiv: *{key}*
  ## Kicker · Titel    beginnt ein Kapitel; der Kicker wird auch die Anker-ID
  > Absatz             eine Randbemerkung (kleiner gesetzt), kein Zitat
  ::: hero … :::       Kicker, # Titel, Lede, dann die Kennzahlen als Liste
  ::: fig fig-xyz [wide] [specimen]
  …                    eine Grafik: optional ein ![alt](bild) zuerst, dann die
  :::                  Bildunterschrift. fig-xyz ist die ID des Charts in story-main.js
  ::: foot Titel … ::: der Fuß der Seite
HTML-Kommentare wie dieser werden beim Bau entfernt; rohes HTML bleibt erhalten.
-->

::: hero
Ein Essay über einen Zitationsgraphen
# Das unabsichtliche Selbstporträt
Was {references} Querverweise über die Philosophie verraten – und was sie über sich selbst verschweigen.

- {entries} Einträge in {volumes} Bänden
- {references} Querverweise
- {resolvedPct} davon eindeutig aufgelöst
- {communities} Regionen im Graphen
:::

Die *Enzyklopädie Philosophie und Wissenschaftstheorie*, herausgegeben von Jürgen Mittelstraß, besteht aus acht alphabetisch geordneten Bänden. Durch die Verweise der Einträge ergibt sich ein Netzwerk aus Pfaden und Verbindungen durch den gesamten Textkorpus. Die Pfeile, im Druck ein kleines <span class="arrow">↑</span> vor dem Stichwort, sind der Gegenstand dieses Textes. Es gibt {references} davon.

Jeder dieser Pfeile ist eine redaktionelle Entscheidung: *Hier*, sagt er, *gehört ein anderer Artikel dazu.* Niemand hat diese Entscheidungen als Ganzes geplant. Sie wurden über Jahrzehnte von Dutzenden Autorinnen und Autoren getroffen, Artikel für Artikel, ohne Blick auf ein Gesamtbild. Legt man sie übereinander, entsteht ein Graph mit {nodes} Knoten und {edges} gerichteten Kanten, in dem jeder Artikel ein Punkt ist und jeder Pfeil eine Linie. Der [Atlas](index.html) zeigt diesen Graphen als Karte.

So konstruiert sich aus den Daten eine Landkarte der Philosophiegeschichte, samt Schulen, Epochengrenzen und den Stellen, an denen sich das Fach bis heute nicht auf einen Begriff einigen kann. Genauere Beobachtung zeigt

## Kapitel 1 · Zitationshäufigkeit

Wer wird am häufigsten zitiert? Am meisten verweisen die Einträge auf Begriffe. Unter den {hubN} meistzitierten Einträgen finden sich keine Personen. An der Spitze steht *{topHub}* mit {topHubDeg} eingehenden Verweisen, dann *{hub2}* ({hub2Deg}) und *{hub3}* ({hub3Deg}). Die meistzitierte Person ist *{topPerson}* mit {topPersonDeg} Verweisen; die *Pythagoreer*, eine Schule, kein Mensch, kommen auf {degPythagoreer}.

::: fig fig-hubs
Eingehende Verweise. Links das Ende der Rangliste, das {lastHubDeg} Verweise braucht; rechts die Personen auf derselben Skala. Der Punkt vor dem Namen zeigt die Region (Kapitel 2). Klick öffnet den Eintrag im Atlas.
:::

Das ist zunächst eine Eigenschaft der Gattung. Ein Sachlexikon verweist auf Sachen; die Biographien sind Beiwerk, kurze Einträge, die klären, wer gemeint ist, wenn im Artikel über Kausalität ein Name fällt. Die Autoren hätten anders verweisen können, auf den Denker statt auf den Begriff, den er geprägt hat, und tun es fast nie. Die Enzyklopädie behandelt Ideen also entkoppelt von den Personen, die sie hervorgebracht, geprägt und weiterentwickelt haben.


> Am anderen Ende der Skala: {uncited} Einträge ({uncitedPct}) werden von keinem anderen Artikel je zitiert – und {uncitedPersonsPct} davon sind Personen. Der mittlere Eintrag hat {median} eingehende Verweise. Es ist ein Graph mit sehr wenigen Zentren und einer sehr breiten Peripherie.

## Kapitel 2 · Strukturen und Zentren

Die Bände sind alphabetisch geordnet. Das hilft, um Artikel zu finden, schafft aber keine relevanten Zusammenhänge zwischen den Einträgen. Die zweite Ordnung steckt in der Struktur des Graphen. Mithilfe eines Betweenness-Algorithmus aus der Graphentheorie lässt sich der Atlas in Gruppen von Artikeln ordnen, die einander häufiger zitieren als den Rest. Er findet {communities} solcher Regionen, von der größten (*{largestComm}*, {largestSize} Einträge) bis zur kleinsten (*{smallestComm}*, {smallestSize}). Die Namen der Regionen sind durch die populärsten Artikel bestimmt.

::: fig fig-chord wide
Verweise zwischen den Regionen. Ein Band läuft von der zitierenden zur zitierten Region, die Spitze zeigt die Richtung; die Breite ist die Zahl der Verweise. Eine Region berühren, um nur ihre Bänder zu sehen. Verweise innerhalb einer Region – {internalPct} aller – sind weggelassen.
:::

Zwei Dinge fallen auf. Erstens ist die Karte innenlastig: {internalPct} aller Verweise bleiben in der eigenen Region. Formale Logik diskutiert mit formaler Logik. Zweitens sind die Beziehungen zwischen Regionen selten symmetrisch. Am einseitigsten: *{flowFrom}* zitiert *{flowTo}* {flowW}-mal, die Gegenrichtung kommt auf {flowBack}. Dabei muss jedoch beachtet werden, dass Zitationspfeile beidseitig entlang der Ideengeschichte verlaufen können: *{flowFrom}* entwickelte sich weit vor den Definitionsversuchen der Begriffe aus *{flowTo}*.

Könnte eine Region nur deshalb zusammenhängen, weil ihre Artikel im selben Band stehen und Autoren gern in die Nachbarschaft verweisen? Nein, wie eine Analyse des Zitierverhaltens zeigt. Jede Zeile ist ein Band, jede Spalte eine Region, jede Zelle der Anteil des Bandes, der in diese Region fällt.

::: fig fig-heatmap
Band gegen Region, als Anteil je Band. Heller ist mehr. Die Zeilen ähneln einander: keine Spalte gehört einem Band. Cramérs V = {cramersV} (χ² = {chi2}, {dof} Freiheitsgrade, n = {heatN}; {unassigned} Einträge außerhalb der zwanzig großen Regionen nicht gezählt).
:::

Cramérs V misst, wie stark zwei Einteilungen zusammenhängen: 0 bei Unabhängigkeit, 1, wenn die eine die andere vollständig bestimmt. Es liegt hier bei {cramersV}. Die oberflächliche Ordnung nach Anfangsbuchstaben beeinflusst also nicht die Struktur, die aus den Verweisen hervorgeht.


## Kapitel 3 · Laute Zentren, leise Brücken

„Wichtig“ ist in einem Netzwerk kein einfacher Begriff. Man kann zählen, wie oft ein Eintrag zitiert wird; man kann aber auch zählen, wie oft ein Eintrag auf dem kürzesten Weg zwischen zwei anderen liegt. So misst man Wichtigkeit als *Vermittlung*, in der Netzwerkanalyse *Betweenness* genannt. Die beiden Maße messen verschiedene Dinge, und das Diagramm zeigt, wie verschieden. Auf der x-Achse sehen wir die absoluten Zitationen, auf der y-Achse den berechneten Betweenness-Centrality-Wert.

::: fig fig-scatter wide
Jeder Punkt ein Eintrag. Beide Achsen sind wurzelskaliert, ein Drittel der Einträge wird nie zitiert. Mit der Maus über die Punktwolke fahren, um Einträge zu lesen; Klick öffnet sie im Atlas.
:::

Die meisten Einträge liegen auf der Diagonalen: es besteht eine eindeutige Korrelation. Den höchsten Betweenness-Wert hat *{btTop}*, ein Eintrag, der nach Verweisen nur auf Rang {btTopDegRank} steht. Interessanter sind die Abweichler. *Rationalität* wird {ratDeg}-mal zitiert, Rang {ratDegRank}, und steht bei der Betweenness auf Rang {ratBtRank}. Das ist ein Begriff, den kaum jemand als Ziel ansteuert, an dem aber sehr viele Wege vorbeiführen: ein Begriff aus den Feldern der Phänomenologie, Ethik und Wissenschaftstheorie. Die Wissenschaftsforschung nennt so etwas ein *Grenzobjekt*, das in verschiedenen Gemeinschaften verschieden verstanden wird und gerade deshalb zwischen ihnen vermitteln kann.

Die auffälligste Brücke ist *Philosophie, buddhistische*: Rang {budBtRank} bei der Betweenness, Rang {budDegRank} bei den Verweisen. Hinter ihr liegt eine ganze Region, *{asiaLabel}* mit {asiaSize} Einträgen. Ihre Artikel verweisen {asiaOut}-mal nach außen, in den Rest der Enzyklopädie. Der Rest der Enzyklopädie verweist jedoch nur {asiaIn}-mal zurück, von denen {asiaTop3Pct} auf nur drei Überblicksartikeln ({asiaTop3}) landen.

Die Autorinnen und Autoren der Artikel über indisches und chinesisches Denken haben ihre Gegenstände in das westliche Vokabular eingebettet, sie verweisen auf <span class="arrow">↑</span>Logik, <span class="arrow">↑</span>Substanz, <span class="arrow">↑</span>Erkenntnistheorie. Die Autoren der Artikel über Logik, Substanz und Erkenntnistheorie haben den Weg zurück selten gefunden. Der Graph zeigt also, wie die westliche Philosophie versucht, philosophische Konzepte aus anderen Kulturkreisen in ihren Systemen zu erklären.

## Kapitel 4 · Zeitachse der Ideengeschichte

In die Berechnung der Regionen ist kein einziges Datum eingegangen. Der Algorithmus kennt nur die Verweise. Trotzdem lässt sich mithilfe der enthaltenen Jahreszahlen fragen, ob die Regionen etwas mit Zeit zu tun haben. Zum Beispiel: *„Kant, Immanuel, Königsberg 22. April 1724, †ebd. 12. Febr. 1804“*. Technisch lässt sich durch das Todeszeichen (Kreuz) diese Art von Daten finden. Für {dated} Einträge ließen sich Geburts- und Sterbejahr auf diese Weise lesen: {datedBio} der {bioTotal} Biographien ({datedPct}), dazu {datedOther} Personen, die das Lexikon aus formalen Gründen nicht als Biographie führt, wie zum Beispiel Sokrates, der keine Werke hinterließ und deshalb keinen *Werke:*-Abschnitt hat. Einträge, bei denen der Text unsicher ist („um 1214 oder 1219“), wurden außen vor gelassen. Damit lässt sich der Zusammenhang der Biographiedaten aus dem Text mit den Strukturdaten des Graphen darstellen.

::: fig fig-strata wide
Jede Zeile eine Region im Atlas, jede Linie ein Leben von der Geburt bis zum Tod, sortiert nach dem Median des Geburtsjahrs. Hier ist die Zeitachse teilweise gedehnt, um die Lesbarkeit zu verbessern.
:::

Wir sehen eine Anordnung nach Epochen. Oben *{firstRow}* mit dem Median {firstMedian}, unten *{lastRow}* mit dem Median {lastMedian}. Dazwischen, in dieser Reihenfolge: Scholastik, Aufklärung, Physik, Naturphilosophie, Kant, Hegel, Wissenschaftstheorie, Mengenlehre. Es ist, bis auf Nuancen, die Reihenfolge, in der Philosophiegeschichte gelehrt wird, die aber nicht explizit in den Daten steht. Datenanalyse und Darstellung beleuchten diesen Zusammenhang.

Von den Personen der Antike liegen {eraAntikeTopPct} in einer einzigen Region (*{eraAntikeTop}*); vom Mittelalter {eraMittelalterTopPct} in *{eraMittelalterTop}*; die Frühe Neuzeit hat ihren Schwerpunkt in *{eraFruehTop}*, das 20. Jahrhundert in *{eraZwanzigTop}*. Das 19. Jahrhundert ist die breiteste Schicht – {eraNeunzehn} Personen, {eraNeunzehnPct} aller datierten – und die am wenigsten konzentrierte: das Jahrhundert, in dem sich die Philosophie in Fächer teilte. Wir sehen auch bedeutende Sekundärliteratur über bestimmte philosophische Schulen und deren Wiederaufleben, Jahrhunderte nach ihren Kernphasen.

> Die längste Lebenslinie gehört *{longestLife}* ({longestYears}, {longestSpan} Jahre).

## Kapitel 5 · Uneindeutigkeit

Nicht jeder Pfeil führt irgendwohin. {unresolved} Verweise zeigen auf Artikel, die es nicht gibt. Und {ambiguous} Verweise ({ambiguousPct}) zeigen auf mehrere Artikel zugleich: Hinter <span class="arrow">↑</span>Implikation kann *Implikation*, *Implikation, strikte* oder *Implikation, relevante* stehen, und der Kontext sagt nicht, welche. Algorithmisch werden solche Verweise als mehrdeutig markiert und alle Kandidaten gelistet. Hier stoßen wir auf eine technische Limitation: einer Expertin oder einem Experten würde der Kontext häufig reichen, um diese Ambiguität aufzulösen. Ein deterministischer Algorithmus kann das nicht.

::: fig fig-ambiguity wide
Links die Begriffe, bei denen der Verweis offen bleibt; in der Mitte die Namen, die mehrere Menschen tragen; rechts die Umkehrung. Alle Links öffnen den Eintrag im Atlas.
:::

Der umstrittenste Begriff des Corpus ist *{topTerm}*: {topTermCount} Verweise, {topTermCands} mögliche Ziele ({topTermList}); der Begriff wird tatsächlich häufig unterschiedlich definiert. Der Graph enthält diese Offenheit als Struktur: Ein Wort, das in der Disziplin mehrere Bedeutungen hat, hat im Graphen mehrere Ziele.

Die zweite Liste behandelt Personennamen. {homonyms} Namen werden von mehreren Menschen zugleich getragen, {homonymsTriple} davon dreifach: {homonymTripleNames}.

Die dritte Liste zeigt die Begriffe mit den meisten Verweisnamen. *{aliasTop}* ist unter {aliasTopCount} weiteren Stichwörtern erreichbar ({aliasTopList}) – die Enzyklopädie hat entschieden, dass diese Unterscheidungen sich einen Artikel teilen, nicht mehrere bekommen.


::: foot Methode
- Knoten sind alle Einträge außer Weiterleitungen; Kanten sind die eindeutig aufgelösten Verweise. Regionen: Leiden-Algorithmus auf der ungerichteten Projektion, Auflösung 2,0. Beides ist der Graph, den auch der Atlas zeigt.
- Betweenness: gerichtet, ungewichtet, über alle kürzesten Wege. Cramérs V aus der Kreuztabelle Band × Region ohne die Einträge außerhalb der zwanzig großen Regionen.
- Lebensdaten: aus dem Kopf jedes Eintrags, verankert am Todeszeichen; Spannen und Alternativen von mehr als einem Jahr wurden ausgelassen. Zwei Einträge ohne jede Epochenangabe (Aristoteles, Cicero) sind von Hand nachgetragen.
- Jede Zahl auf dieser Seite wird beim Bau der Daten berechnet und von einem unabhängigen Prüfskript nachgerechnet. Stand der Daten: {generated}.

[Zum Atlas](index.html) · [Quellcode und Daten](https://github.com/jan-c-buchkremer/philosophie-lexikon)
:::
