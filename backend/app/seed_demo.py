from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .database import Base, SessionLocal, engine
from .models import Auditorium, Movie, Screening, Seat

FILMS=[
    {"title":"Yulduzlar orasida","synopsis":"A quiet astronomer finds an unexpected message in the night sky and sets out to answer it.","duration_minutes":116,"genre":"Sci-fi · Drama","age_rating":"12+","language":"O‘zbekcha","poster_url":"https://images.unsplash.com/photo-1462331940025-496dfbfc7564?auto=format&fit=crop&w=800&q=85"},
    {"title":"So‘nggi bekat","synopsis":"Two strangers miss the last train and discover that a wrong turn can lead somewhere wonderful.","duration_minutes":101,"genre":"Drama · Mystery","age_rating":"16+","language":"O‘zbekcha","poster_url":"https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=800&q=85"},
    {"title":"Bahor kelganda","synopsis":"A young chef returns home to save the family café, one table and one old recipe at a time.","duration_minutes":108,"genre":"Romance · Comedy","age_rating":"12+","language":"O‘zbekcha","poster_url":"https://images.unsplash.com/photo-1470252649378-9c29740c9fa8?auto=format&fit=crop&w=800&q=85"},
    {"title":"Kichik qahramonlar","synopsis":"A curious fox and a careful hedgehog cross the valley to bring a lost star home.","duration_minutes":92,"genre":"Animation · Family","age_rating":"6+","language":"O‘zbekcha","poster_url":"https://images.unsplash.com/photo-1478760329108-5c3ed9d495a0?auto=format&fit=crop&w=800&q=85"},
    {"title":"Qorong‘u shahar","synopsis":"A sound engineer follows a midnight broadcast through the streets she thought she knew.","duration_minutes":122,"genre":"Thriller · Mystery","age_rating":"16+","language":"O‘zbekcha","poster_url":"https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=800&q=85"},
    {"title":"Yurakdagi ohang","synopsis":"A retired piano teacher and a street musician trade songs and change each other’s tune.","duration_minutes":113,"genre":"Drama · Music","age_rating":"12+","language":"O‘zbekcha","poster_url":"https://images.unsplash.com/photo-1507838153414-b4b713384a76?auto=format&fit=crop&w=800&q=85"},
]

def main():
    Base.metadata.create_all(engine)
    tz=ZoneInfo("Asia/Tashkent")
    with SessionLocal() as db:
        if db.scalar(select(Movie.id).limit(1)):
            print("Cinema sample data already exists")
            return
        films=[Movie(**data) for data in FILMS]
        halls=[]
        for name,count in (("Katta zal",96),("Oila zali",72),("Premier zal",48)):
            cols=12 if count==96 else 12 if count==72 else 8
            rows=count//cols
            room=Auditorium(name=name,cinema_name="Parda Cinema",city="Tashkent",
                address="Amir Temur Avenue, Tashkent",timezone="Asia/Tashkent")
            room.seats=[Seat(row_label=chr(65+r),seat_number=n,
                seat_type="premium" if r < 2 else "standard") for r in range(rows) for n in range(1,cols+1)]
            halls.append(room)
        db.add_all([*films,*halls]);db.flush()
        screening_rows=[]
        now=datetime.now(tz)
        for day_offset in range(7):
            day=(now+timedelta(days=day_offset)).date()
            for hall_index,room in enumerate(halls):
                for slot_index,hour in enumerate((10,13,16,19)):
                    local_start=datetime.combine(day,time(hour,0),tzinfo=tz)
                    if local_start<=now+timedelta(minutes=15):continue
                    film=films[(day_offset*2+slot_index+hall_index)%len(films)]
                    start_utc=local_start.astimezone(timezone.utc)
                    screening_rows.append(Screening(movie_id=film.id,auditorium_id=room.id,
                        starts_at=start_utc,ends_at=start_utc+timedelta(minutes=film.duration_minutes),
                        base_price=(35000 if room.name=="Premier zal" else 25000 if room.name=="Oila zali" else 30000)))
        db.add_all(screening_rows);db.commit()
        print(f"Seeded {len(films)} fictional sample films, {len(halls)} halls, {len(screening_rows)} screenings")

if __name__=="__main__":main()
