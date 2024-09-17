# Predictions

This folder contains the last available predictions made by the model. See the top level README for how to add these to Home Assistant.

Live version: [https://nordpool-predict-fi.web.app](https://nordpool-predict-fi.web.app)

## prediction.json for ApexCharts

The array consists of hourly pairs.

- The first number is UNIX time in milliseconds, UTC, directly compatible with Apex Charts.
- The second number is price prediction in euro cents, with VAT.

Sample contents:

```json
[[1708351200000.0, 10.518398524597846], [1708354800000.0, 10.310836452494842], [1708358400000.0, 10.689536373878193], [1708362000000.0, 11.01924045800625], [1708365600000.0, 11.292687833420601], [1708369200000.0, 10.552406542055508], [1708372800000.0, 9.617814126711597], ...
```

## averages.json for ApexCharts

Same as above, but the timestamp (UTC) matches with the beginning of the Finnish day, and includes the average price for the starting days.

Sample contents:

```json
[[1708300800000.0, 9.563463154063907], [1708387200000.0, 8.957010347447694], [1708473600000.0, 6.178894845644102], [1708560000000.0, 3.004293814227683], [1708646400000.0, 2.4571863121034263], [1708732800000.0, 2.122324842971843]]
```

## narration.md

Same as above, but narrated (in Finnish) by a large language model. In the prompt, you could ask it to produce the response in English instead.

Sample contents:

> Tiistaina pörssisähkön hinta vaihtelee 7–12 sentin välillä, keskimäärin 10 senttiä per kilowattitunti. Tuulivoiman tuotanto on 308–688 megawattia, keskimäärin 467 megawattia.
>
> Keskiviikkona sähkön hinta on alhainen, 3–7 senttiä, keskimäärin 5 senttiä per kilowattitunti. Tuulivoiman tuotanto on suurimmillaan viikolla, 902–4105 megawattia, keskimäärin 2226 megawattia.
>
> Torstaina sähkön hinta on edelleen alhainen, 2–4 senttiä, keskimäärin 3 senttiä per kilowattitunti. Tuulivoiman tuotanto on korkeimmillaan koko viikolla, 3393–4508 megawattia, keskimäärin 3932 megawattia.
>
> Perjantaina sähkön hinta pysyy alhaisena, 2–3 sentissä, keskimäärin 2 senttiä per kilowattitunti. Tuulivoiman tuotanto on edelleen suurta, 4390–5695 megawattia, keskimäärin 5316 megawattia.
>
> Viikonloppuna sähkön hinta on edelleen alhainen, 1–3 senttiä, keskimäärin 2 senttiä per kilowattitunti. Tuulivoiman tuotanto on vakaata, 4010–6003 megawattia, keskimäärin 5004 megawattia.
>
> Koko ajanjakson aikana sähkön hinta pysyy pääosin alhaisena, mikä on positiivista kuluttajille. Tuulivoiman tuotanto vaihtelee päivittäin, mutta pysyy suurena lähes koko viikon ajan. Tämä voi auttaa tasaamaan sähkön hintoja ja vähentämään riippuvuutta muista energialähteistä.

## index.html

Fetches the latest predictions from this repo and renders them as a web page.
