// ===== tabla: hotspots =====
let
    Tendencia = Json.Document(Web.Contents(ApiUrl, [RelativePath = "live/trend"])),
    Ventanas = List.Transform(Tendencia[results], each Text.Start(_[window_start], 10)),
    Cargar = (w as text) as list =>
        let
            r = Json.Document(Web.Contents(ApiUrl, [RelativePath = "live/hotspots", Query = [window = w, limit = "500"]]))
        in
            List.Transform(r[results], each [
                geohash = _[geohash],
                ventana = w,
                window_start = DateTime.FromText(w & "T00:00:00"),
                n = _[n],
                negatives = _[negatives],
                pct_negative = _[pct_negative],
                prev_pct_negative = _[prev_pct_negative],
                delta_pp = _[delta_pp],
                hotspot = _[hotspot],
                estado = if _[hotspot] then "Hotspot" else "Normal",
                lat = _[lat],
                lon = _[lon]
            ]),
    Filas = List.Combine(List.Transform(Ventanas, Cargar)),
    Tabla = Table.FromRecords(Filas, type table [geohash = text, ventana = text, window_start = datetime, n = Int64.Type, negatives = Int64.Type, pct_negative = number, prev_pct_negative = nullable number, delta_pp = nullable number, hotspot = logical, estado = text, lat = number, lon = number])
in
    Tabla

// ===== tabla: trend =====
let
    r = Json.Document(Web.Contents(ApiUrl, [RelativePath = "live/trend"])),
    Filas = List.Transform(r[results], each [
        window_start = DateTime.FromText(Text.Start(_[window_start], 19)),
        ventana = Text.Start(_[window_start], 10),
        n = _[n],
        negatives = _[negatives],
        pct_negative = _[pct_negative],
        cells = _[cells],
        hotspots = _[hotspots]
    ]),
    Tabla = Table.FromRecords(Filas, type table [window_start = datetime, ventana = text, n = Int64.Type, negatives = Int64.Type, pct_negative = nullable number, cells = Int64.Type, hotspots = Int64.Type])
in
    Tabla

// ===== tabla: alerts =====
let
    r = Json.Document(Web.Contents(ApiUrl, [RelativePath = "alerts", Query = [limit = "500"]])),
    Filas = List.Transform(r[results], each [
        business_id = _[business_id],
        name = _[name],
        main_category = _[main_category],
        probability = _[probability],
        as_of = DateTime.FromText(Text.Start(_[as_of], 19)),
        lat = _[lat],
        lon = _[lon],
        n_reviews = _[features][n_reviews],
        avg_stars = _[features][avg_stars],
        pct_neg_6m = _[features][pct_neg_6m],
        trend_neg = _[features][trend_neg],
        n_reviews_6m = _[features][n_reviews_6m],
        days_since_last = _[features][days_since_last],
        competitors_500m = _[features][competitors_500m]
    ]),
    Tabla = Table.FromRecords(Filas, type table [business_id = text, name = nullable text, main_category = nullable text, probability = number, as_of = datetime, lat = number, lon = number, n_reviews = Int64.Type, avg_stars = number, pct_neg_6m = number, trend_neg = number, n_reviews_6m = Int64.Type, days_since_last = Int64.Type, competitors_500m = Int64.Type])
in
    Tabla

// ===== tabla: survival =====
let
    Grupos = (dim as text, etiqueta as text, ruta as text) as list =>
        let
            idx = Json.Document(Web.Contents(ApiUrl, [RelativePath = "survival", Query = [dimension = dim, status = "ok", limit = "8"]])),
            nombres = List.Transform(idx[results], each if dim = "zone" then _[zone] else _[category]),
            curva = (g as text) as list =>
                let
                    r = Json.Document(Web.Contents(ApiUrl, [RelativePath = ruta & Uri.EscapeDataString(g)]))
                in
                    List.Transform(r[curve], each [
                        grupo = g,
                        tipo = etiqueta,
                        years = _[t] / 365,
                        t_days = _[t],
                        s = _[s],
                        lo = _[lo],
                        hi = _[hi],
                        at_risk = _[at_risk]
                    ])
        in
            List.Combine(List.Transform(nombres, curva)),
    Filas = List.Combine({Grupos("category", "Categoría", "survival/"), Grupos("zone", "Zona", "survival/zone/")}),
    Tabla = Table.FromRecords(Filas, type table [grupo = text, tipo = text, years = number, t_days = Int64.Type, s = number, lo = number, hi = number, at_risk = Int64.Type])
in
    Tabla

// ===== tabla: health =====
let
    r = Json.Document(Web.Contents(ApiUrl, [RelativePath = "health", ManualStatusHandling = {503}])),
    s = r[streaming],
    Fila = [
        status = r[status],
        kafka = r[services][kafka],
        mongo = r[services][mongo],
        streaming_status = s[status],
        consumer_lag = Record.FieldOrDefault(s, "consumer_lag", null),
        last_batch = Record.FieldOrDefault(s, "last_batch", null),
        seconds_since_heartbeat = Record.FieldOrDefault(s, "seconds_since_heartbeat", null),
        model_version = Record.FieldOrDefault(s, "model_version", null),
        commit = r[commit]
    ],
    Tabla = Table.FromRecords({Fila}, type table [status = text, kafka = text, mongo = text, streaming_status = text, consumer_lag = nullable Int64.Type, last_batch = nullable Int64.Type, seconds_since_heartbeat = nullable Int64.Type, model_version = nullable text, commit = text])
in
    Tabla
