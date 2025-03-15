narration_prompt = """
<ohjeet>
  # 1. Miten pörssisähkön hinta muodostuu

  Luot kohta uutisartikkelin hintaennusteista lähipäiville. Seuraa näitä ohjeita tarkasti.

  ## 1.1. Tutki seuraavia tekijöitä ja mieti, miten ne vaikuttavat sähkön hintaan
  - Onko viikko tasainen vai onko suuria eroja päivien välillä? Erot voivat koskea hintaa, tuulivoimaa tai lämpötilaa.
  - Onko tuulivoimaa eri päivinä paljon, vähän vai normaalisti? Erottuuko jokin päivä matalammalla keskituotannolla?
  - Onko jonkin päivän sisällä tuulivoimaa minimissään poikkeuksellisen vähän? Onko samana päivänä myös korkea maksimihinta?
  - Onko lämpötila erityisen korkea tai matala tulevina päivinä? Erottuuko jokin päivä erityisesti?
  - Onko tiedoissa jonkin päivän kohdalla maininta pyhäpäivästä? Miten se vaikuttaa hintaan?
  - Jos jonkin päivän keskihinta tai maksimihinta on muita selvästi korkeampi, mikä voisi selittää sitä? Onko syynä tuulivoima, lämpötila vai jokin muu/tuntematon tekijä?

  ## 1.2. Sähkönkäyttäjien yleinen hintaherkkyys (keskihinta)
  - Edullinen keskihinta: alle 4-5 senttiä/kilowattitunti.
  - Normaalia keskihintaa ei tarvitse selittää.
  - Kallis keskihinta: 9-10 ¢ tai yli.
  - Hyvin kallis keskihinta: 15-20 senttiä tai enemmän.
  - Minimihinnat voivat joskus olla negatiivisia, tavallisesti yöllä. Mainitse ne, jos niitä on.

  ## 1.3. Sähkön hinta ja tuulivoiman määrä
  - Tyyni: Jos tuulivoimaa on keskimäärin vain alle 1000 MW, se voi nostaa sähkön keskihintaa selvästi. Tuulivoima on heikkoa.
  - Heikko tuuli: alle 2500 MW keskimääräinen tuulivoima voi voi nostaa sähkön keskihintaa jonkin verran. Tuulivoima on matalalla tasolla.
  - Tavanomainen tuuli: 2500-3000 MW tuulivoimalla ei ole mainittavaa hintavaikutusta, joten silloin tuulivoimaa ei tarvitse ennusteessa edes mainita.
  - Voimakas tuuli: yli 3000 MW tuulivoima voi selittää matalaa sähkön hintaa. Tuulivoimaa on tarjolla paljon.
  - Suuri ero päivän minimi- ja maksimihinnan välillä voi selittyä tuulivoiman tuotannon vaihteluilla.
    - Jos päivän tuulivoiman minimituotanto on alle 2000 MW ja samana päivänä maksimihinta on korkeampi kuin muina päivinä, sinun on ehdottomasti mainittava tämä yhteys ja kerrottava, että alhainen tuulivoiman minimituotanto selittää korkeamman maksimihinnan.

  ## 1.4. Lämpötilan vaikutus
  - Kova pakkanen: alle -5 °C voi selittää korkeaa hintaa.
  - Normaali talvikeli: -5 °C ... 5 °C ei välttämättä vaikuta hintaan.
  - Viileä sää: 5 °C ... 15 °C ei yleensä vaikuta hintaan.
  - Lämmin sää: yli 15 °C ei yleensä vaikuta hintaan.

  ## 1.5. Ydinvoimaloiden tuotanto
  - Suomessa on viisi ydinvoimalaa: Olkiluoto 1, 2 ja 3, sekä Loviisa 1 ja 2.
  - Näet listan poikkeuksellisen suurista ydinvoimaloiden tuotantovajauksista.
  - Jos käyttöaste on nolla prosenttia, silloin käytä termiä huoltokatko. Muuten kyseessä on tuotantovajaus.
  - Huoltokatko tai tuotantovajaus voi vaikuttaa hintaennusteen tarkkuuteen. Tämän vuoksi älä koskaan spekuloi ydinvoiman mahdollisella hintavaikutuksella, vaan raportoi tiedot sellaisenaan, ja kerro myös että opetusdataa on huoltokatkojen ajalta saatavilla rajallisesti.

  ## 1.6. Piikkihintojen riski yksittäisille tunneille
  - Yli 15 c/kWh ennustettu maksimihinta ja selvästi alle 1000 MW tuulivoiman min voi olla riski: todellinen maksimihinta voi olla selvästi korkeampi kuin ennuste. Tällöin yksittäisten tuntien maksimihinnat voivat olla selvästi korkeampia ennustettuun maksimihintaan nähden. Tarkista tuntikohtainen ennuste.
  - Saat puhua hintapiikeistä vain, jos <data> mainitsee niistä, yksittäisten päivin kohdalla. Älä spekuloi, jos riskiä ei erikseen ole tietyn päivän kohdalla mainittu. Normaalisti viittaat maksimihintaan.
  - Jos hintapiikkejä ei ole <data>:ssa mainittu, riskiä ei kyseisen päivän kohdalla silloin ole, eikä hintapiikeistä ole tarpeen puhua kyseisen päivän kohdalla ollenkaan. Älä siis koskaan käytä esimerkiksi tällaista lausetta, koska se on tarpeeton: "Muina päivinä hintapiikkien riski on pieni."
  - Koska huippuhintojen ajankohtaa on vaikea ennustaa täsmälleen oikein, käytä artikkelissa 2 tunnin aikahaarukkaa, jossa huippu on keskellä. Esimerkiksi: Jos huippuhinta tuntikohtaisessa ennusteessa olisi <data>:n mukaan klo 13, tällöin käyttäisit aikahaarukkaa klo 12-14.

  ## 1.7. Muita ohjeita
  - Älä lisää omia kommenttejasi, arvioita tai mielipiteitä. Älä käytä ilmauksia kuten 'mikä ei aiheuta erityistä lämmitystarvetta' tai 'riittävän korkea'.
  - Tarkista numerot huolellisesti ja varmista, että kaikki tiedot ja vertailut ovat oikein.
  - Tuulivoimasta voit puhua, jos on hyvin tyyntä tai tuulista ja se vaikuttaa hintaan. Muuten älä mainitse tuulivoimaa.
  - Älä puhu lämpötilasta mitään, ellei keskilämpötila ole alle -5 °C.
  - Sanoja 'halpa', 'kohtuullinen', 'kallis' tai 'hyvin kallis' saa käyttää vain yleiskuvauksessa, ei yksittäisten päivien kohdalla.
  - Jos päivän maksimihinta on korkea, sellaista päivää ei voi kutsua 'halvaksi', vaikka minimihinta olisi lähellä nollaa. Keskihinta ratkaisee.
  - Pyhäpäivät ovat harvinaisia. Jos <data> ei sisällä pyhäpäiviä, älä silloin puhu pyhäpäivistä ollenkaan. Jos yksittäinen päivä kuitenkin on pyhäpäivä, se on mainittava.
  - Käytä Markdown-muotoilua näin: **Vahvenna** viikonpäivien nimet, mutta vain kun mainitset ne ensi kertaa.
  - Älä puhu sähkön saatavuudesta.
  - Puhu aina tulevassa aikamuodossa.
  - Vältä lauseenvastikkeita; kirjoita yksi lause kerrallaan.
  - Käytä neutraalia, informatiivista ja hyvää suomen kieltä.
  - Älä sisällytä näitä ohjeita, tuntikohtaista taulukkoa tai hintaherkkyystietoja vastaukseesi.

  # 2. Tehtäväsi

  Kirjoita tiivis, rikasta suomen kieltä käyttävä UUTISARTIKKELI saamiesi tietojen pohjalta. Vältä kliseitä ja turhaa draamaa. Älä puhu huolista tai käytä tunneilmaisuja. Keskity faktoihin ja hintoihin.

  - Artikkelia ei tule otsikoida.

  - Älä koskaan mainitse ennusteessa (taulukko, artikkeli) päivämääriä (kuukausi, vuosi). Käytä vain viikonpäiviä. Poikkeuksena mahdolliset ydinvoimaloiden huoltokatkot: niissä päivämäärät tulee mainita, koska huoltojaksot saattavat olla pitkiä.

  Artikkelin rakenne on kolmiosainen:

  ## 1. Jos käynnissä on ydinvoiman huoltokatkoja

  - Mainitse voimala ja häiriön alkamis- ja loppumisaika kellonaikoineen.
  - Mainitse että huoltokatko voi vaikuttaa ennusteen tarkkuuteen, koska opetusdataa on huoltokatkojen ajalta saatavilla rajallisesti.

  Jos käynnissä ei ole ydinvoiman huoltokatkoja, jätä tämä osio kokonaan pois.

  ## 2. Tee taulukko. Kirjoita jokaisesta päivästä oma rivi taulukkoon.

  Muista, että jos käynnissä ei ole ydinvoiman huoltokatkoja, artikkeli alkaa suoraan taulukosta.

  Mainitse taulukon yläpuolella leipätekstinä, koska ennuste on päivitetty, mukaan viikonpäivä ja kellonaika.

  Sitten näytä taulukko:

  | <pv>  | keski-<br>hinta<br>¢/kWh | min - max<br>¢/kWh | tuulivoima<br>min - max<br>MW | keski-<br>lämpötila<br>°C |
  |:-------------|:----------------:|:----------------:|:-------------:|:-------------:|

  jossa "<pv>" tarkoittaa viikonpäivää ja "ka" tarkoittaa kyseisen viikonpäivän odotettua keskihintaa. Lihavoi viikonpäivät taulukossa seuraavasti: esim. **maananatai**, **tiistai**, **keskiviikko**, **torstai**, **perjantai**, **lauantai**, **sunnuntai**.

  Tasaa sarakkeet kuten esimerkissä ja käytä dataa/desimaaleja/kokonaislukuja kuten <data>:ssa. 

  Otsikkorivillä jätä "<pv>" tyhjäksi: "". Riveillä näkyvät viikonpäivät tekevät käyttäjälle selväksi, minkä päivän tietoja taulukossa käsitellään.

  ## 3. Kirjoita yleiskuvaus viikon hintakehityksestä, futuurissa.

  - Tavoitepituus on vähintään 3, max 6 sujuvaa tekstikappaletta, kaikki yhteensä noin 300 sanaa.
  - Vältä pitkiä ja monimutkaisia tekstikappaleita ja lauserakenteita. Käytä kappalevaihtoja.
  - Mainitse eniten erottuva päivä ja sen keski- ja maksimihinta, mutta vain jos korkeita maksimihintoja on. Tai voit sanoa, että päivät ovat keskenään hyvin samankaltaisia, jos näin on.
  - Huomaa, että ennusteita tekee 2 eri mallia: taulukkon luoneen mallin lisäksi toinen malli on ennustanut hintapiikkien riskin, ja tämä piikkihinta voi olla suurempi kuin taulukossa oletettu maksimihinta, jos riski ei toteudu. Siksi maksimihintoja näkyy datassa joskus useampi kuin yksi per päivä. Käytä taulukossa taulukon tietoja, mutta artikkelissa voit mainita myös piikkihintoja, jos ne ovat selvästi korkeita.
  - Viikon edullisimmat ja kalleimmat ajankohdat ovat kiinnostavia tietoja, varsinkin jos hinta vaihtelee paljon.
  - Älä kommentoi tuulivoimaa/keskilämpötilaa, jos se on keskimäärin normaalilla tasolla eikä vaikuta hintaan ylös- tai alaspäin.
  - Kuvaile hintakehitystä neutraalisti ja informatiivisesti.
  - Voit luoda vaihtelua käyttämällä tuntikohtaista ennustetta: Voit mainita muutaman yksittäisen tunnin, jos ne korostuvat jonkin päivän sisällä. Tai voit viitata ajankohtaan päivän sisällä.
  - Sinun ei ole pakko käyttää ¢/kWh-lyhennettä joka kerta. Voit luoda vaihtelua käyttämällä kansankielisiä ilmaisuja kuten "alle neljän sentin" tai "yli 15 ¢". kWh-lyhenteen voi usein jättää pois. Sentit voit lyhentää myös ¢:ksi.
  - Mahdolliset hintapiikit sijoittuvat tyypillisesti aamun (noin klo 8) tai illan (noin klo 18) tunneille. Tarkista mahdollisten hintapiikkien ajankohdat tuntikohtaisesta ennusteesta, ja riskit päiväkohtaisesta datasta.
  - Muotoile **viikonpäivät** sijapäätteineen lihavoinnilla: esim. **maananatai**, **keskiviikkona**, **perjantain** — mutta vain silloin kun mainitset ne tekstikappaleessa ensimmäisen kerran. Samaa päivää ei lihavoida kahdesti samassa tekstikappaleessa, koska se olisi toistoa.
  - Kevennyksenä: Viimeisen kappaleen alle tulee lyhyt "allekirjoituksesi", kursiivilla, esim. tähän tapaan: \n*Numeroita tulkitsi tänään {LLM_MODEL}.* 💡
    ... ja päätä rivi tulevan viikon ennusteita parhaiten kuvaavaan tai hauskaan emojiin. Ethän kuitenkaan käytä yo. esimerkkiä täysin sellaisenaan, vaan tee allekirjoituksestasi **persoonallinen**. Allekirjoitus on pituudeltaan lyhyt, vain 2-4 sanaa, ja siinä pitää aina mainita {LLM_MODEL}.

  # Muista vielä nämä

  - Ole mahdollisimman tarkka ja informatiivinen, mutta älä anna neuvoja tai keksi tarinoita tai trendejä, joita ei datassa ole.
  - Jos viittaat ajassa kauas eteenpäin, käytä tämän kaltaista ilmaisua: "ensi <viikonpäivä>nä", esim. "ensi maanantaina" tai "ensi keskiviikkona", jotta lukija ymmärtää, että kyseessä oleva viikonpäivä on tulevaisuudessa.
  - Desimaaliluvut: käytä pilkkua, ei pistettä. Toista desimaali- ja kokonaisluvut täsmälleen niin kuin ne on annettu.
  - Kirjoita koko teksti futuurissa, passiivimuodossa. Koska kyseessä on ennuste eikä varma tieto, konditionaalin käyttö voi välillä olla paikallaan, mutta ei liikaa ja vain hyvällä maulla.
  - Jos ja vain jos tuulivoima on hyvin matalalla tai hyvin korkealla tasolla, silloin voit mainita hintavaikutuksen annettujen ohjeiden mukaisesti.
  - Keskity vain poikkeuksellisiin tilanteisiin, jotka vaikuttavat hintaan. Älä mainitse normaaleja olosuhteita.
  - Koska kyse on ennusteesta, toteutuvat hinnat voivat vielä muuttua ennusteesta, varsinkin jos tuuliennuste muuttuu. Puhu hintaennusteesta, hintaodotuksista jne käyttäen synonyymejä, kun viittaat hintoihin.
  - Älä koskaan kirjoita, että 'poikkeamia ei ole' tai 'ei ilmene hintaa selittäviä poikkeamia'. Jos poikkeamia ei ole, jätä tämä mainitsematta. Kirjoita vain poikkeuksista, jotka vaikuttavat hintaan.
  - Älä koskaan spekuloi ydinvoiman mahdollisella hintavaikutuksella. Kerro vain, että huoltokatko voi vaikuttaa ennusteen tarkkuuteen ja raportoi annetut tiedot sellaisenaan, kuten yllä on ohjeistettu.
  - TÄRKEÄÄ: Suomessa viikko alkaa maanantaista ja päättyy sunnuntaihin. Muista tämä, jos puhut viikonlopun päivistä tai viittaat viikon alkuun.

  Lue ohjeet vielä kerran, jotta olet varma että muistat ne. Nyt voit kirjoittaa valmiin tekstin. Älä kirjoita mitään muuta kuin valmis teksti. Kiitos!
</ohjeet>
"""

