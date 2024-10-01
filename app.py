from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import os
import datetime
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from dotenv import load_dotenv
import time
from collections import defaultdict
import statistics
from flask_cors import CORS 

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('SECRET_KEY', 'your_secret_key_here')

# Shared OpenAI ChatGPT API Call
def call_chatgpt(prompt):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 150
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

# Google Maps API: Latitude/Longitude Lookup
def get_lat_long(city_name):
    api_key = os.getenv('GOOGLE_API_KEY')
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {'address': city_name, 'key': api_key}
    response = requests.get(base_url, params=params)
    response.raise_for_status()
    data = response.json()
    if data['results']:
        latitude = data['results'][0]['geometry']['location']['lat']
        longitude = data['results'][0]['geometry']['location']['lng']
        return latitude, longitude
    else:
        return None, None
 
# 영어에서 한국어로 날씨 설명을 변환하는 함수
def translate_weather_description(description):
    translations = {
        "clear sky": "맑음",
        "few clouds": "약간 구름",
        "scattered clouds": "구름 조금",
        "broken clouds": "구름 많음",
        "shower rain": "소나기",
        "rain": "비",
        "light rain":"가벼운 비",
        "overcast clouds" :"흐림",
        "thunderstorm": "천둥번개",
        "snow": "눈",
        "mist": "안개"
    }
    return translations.get(description, description)  # 변환할 단어가 없으면 그대로 반환

# OpenWeather API: 일별 날씨 데이터로 변환
def get_weather_data(latitude, longitude, start_timestamp, end_timestamp):
    api_key = os.getenv('OPENWEATHER_API_KEY')
    url = "https://history.openweathermap.org/data/2.5/history/city"
    params = {
        'lat': latitude,
        'lon': longitude,
        'type': 'hour',
        'start': start_timestamp,
        'end': end_timestamp,
        'appid': api_key,
        'lang': 'kr'  # API 응답을 한국어로 설정
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    raw_data = response.json()

    # 날짜별로 데이터를 그룹화할 딕셔너리
    daily_weather = defaultdict(list)

    # 시간별 데이터를 받아와서 날짜별로 그룹화
    for entry in raw_data.get('list', []):
        dt = entry['dt']
        date = datetime.datetime.utcfromtimestamp(dt).strftime('%Y-%m-%d')  # 날짜만 추출

        main_info = entry['main']
        temperature = main_info.get('temp')
        feels_like = main_info.get('feels_like')
        humidity = main_info.get('humidity')
        rain = entry.get('rain', {}).get('1h', 0)  # 강수량, 없으면 0으로
        weather_description = entry['weather'][0]['description']

        # 영어 날씨 설명을 한국어로 변환
        weather_description_korean = translate_weather_description(weather_description)

        # 해당 날짜에 관련된 정보를 리스트로 추가
        daily_weather[date].append({
            'temperature': temperature,
            'feels_like': feels_like,
            'humidity': humidity,
            'rain': rain,
            'weather_description': weather_description_korean  # 한국어로 변환된 날씨 설명 사용
        })

    # 각 날짜별로 데이터를 요약 (평균 온도, 총 강수량, 가장 빈번한 날씨 상태)
    weather_info = []
    for date, entries in daily_weather.items():
        avg_temp = statistics.mean([entry['temperature'] for entry in entries])  # 평균 온도
        avg_feels_like = statistics.mean([entry['feels_like'] for entry in entries])  # 평균 체감 온도
        avg_humidity = statistics.mean([entry['humidity'] for entry in entries])  # 평균 습도
        total_rain = sum(entry['rain'] for entry in entries)  # 총 강수량
        weather_description = statistics.mode([entry['weather_description'] for entry in entries])  # 가장 빈번한 날씨 상태

        # 일별 요약 데이터를 추가
        weather_info.append({
            'date': date,
            'temperature': avg_temp,
            'feels_like': avg_feels_like,
            'humidity': avg_humidity,
            'rain': total_rain,
            'weather_description': weather_description
        })

    return weather_info


# Google Places API: Restaurant and Hotel Lookup
def get_restaurants(city_name, api_key):
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json?"
    query = f"restaurants in {city_name}"
    response = requests.get(base_url + 'query=' + query + '&key=' + api_key + '&language=ko')
    response.raise_for_status()
    return response.json()

def get_hotels(city_name, api_key):
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json?"
    query = f"hotels in {city_name}"
    response = requests.get(base_url + 'query=' + query + '&key=' + api_key + '&language=ko')
    response.raise_for_status()
    return response.json()

# 한국관광공사 API: 근처 관광지 정보 가져오기
def get_tour_info(latitude, longitude, radius=1000, content_type_id=12):
    api_key = os.getenv('TOUR_API_KEY')
    url = f"http://apis.data.go.kr/B551011/KorService1/locationBasedList1?serviceKey={api_key}&numOfRows=10&pageNo=1&MobileOS=ETC&MobileApp=AppTest&mapX={longitude}&mapY={latitude}&radius=7000&contentTypeId={content_type_id}&_type=json"

    response = requests.get(url)

    if response.status_code == 200:
        try:
            if response.headers.get('Content-Type') == 'application/json':
                data = response.json()

                # 검증
                response_data = data.get('response')
                if isinstance(response_data, dict):
                    body = response_data.get('body')
                    if isinstance(body, dict):
                        items = body.get('items')
                        print("Actual 'items' content:", items)  # items의 실제 내용을 출력
                        if isinstance(items, dict):
                            return items.get('item', [])
                        elif isinstance(items, list):
                            # 'items'가 리스트일 경우, 그대로 반환
                            return items
                        else:
                            print("Error: 'items' is not a dictionary or list. Actual content:", items)
                            return []
                    else:
                        print("Error: 'body' is not a dictionary. Actual content:", body)
                        return []
                else:
                    print("Error: 'response' is not a dictionary. Actual content:", response_data)
                    return []
            else:
                print("Error: Response is not in JSON format.")
                print("Raw response content:", response.text)
                return []
        except ValueError:
            print("Error: Failed to parse JSON. Raw response content:")
            print(response.text)
            return []
    else:
        print(f"Tour API Error: {response.status_code}, {response.text}")
        return []

#국내여행 프롬프트 
def generate_domestic_prompt(start_date, end_date, companions, departure_city, transportation, style):
    prompt = (
        f"Recommend a specific city in South Korea for someone traveling with {companions}. "
        f"They will be departing from {departure_city}, "
        f"and will be traveling from {start_date} to {end_date}. "
        f"They prefer to use {transportation} and enjoy {style} style trips. "
        f"Only recommend a city, not a province or a large region like Gangwon-do. "
        f"The recommendation should be a city suitable for tourism, not a broad area."
        f"please print only city name in korean"
    )
    return prompt


# Main route
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

# Domestic travel survey
@app.route('/domestic', methods=['GET', 'POST'])
def domestic_survey():
    if request.method == 'POST':
        # Collect form data
        session['start_date'] = request.form['start_date']
        session['end_date'] = request.form['end_date']
        session['companions'] = request.form['companions']
        session['departure_city'] = request.form['departure_city']
        session['transportation'] = request.form['transportation']
        session['style'] = request.form['style']

        # Generate prompt and get city recommendation
        prompt = generate_domestic_prompt(
            session['start_date'], session['end_date'], session['companions'],
            session['departure_city'], session['transportation'], session['style']
        )
        city_name = call_chatgpt(prompt)['choices'][0]['message']['content'].strip()
        session['city_name'] = city_name

        # Get latitude/longitude and tour information
        latitude, longitude = get_lat_long(city_name)
        if latitude and longitude:
            # Get nearby tourist spots using coordinates
            tour_info = get_tour_info(latitude, longitude)

            # Get nearby restaurants and hotels using city name
            api_key = os.getenv('GOOGLE_API_KEY')
            restaurants_data = get_restaurants(city_name, api_key)
            hotels_data = get_hotels(city_name, api_key)

            # Extract relevant restaurant and hotel information
            restaurants_info = [{'name': restaurant['name'], 'address': restaurant.get('formatted_address', '주소 없음')} for restaurant in restaurants_data['results']]
            hotels_info = [{'name': hotel['name'], 'address': hotel.get('formatted_address', '주소 없음')} for hotel in hotels_data['results']]

            # Render template with city name, tour info, restaurant, and hotel information
            return render_template(
                'results_domestic.html', 
                city_name=city_name, 
                tour_info=tour_info,
                restaurants=restaurants_info,
                hotels=hotels_info
            )
        else:
            return f"<pre>City: {city_name}\nUnable to find latitude and longitude.</pre>"

    return render_template('form_domestic.html')

# International travel survey
@app.route('/international', methods=['GET', 'POST'])
def international_survey():
    if request.method == 'POST':
        # 사용자 입력 데이터 수집 및 세션에 저장
        session['start_date'] = request.form['start_date']
        session['end_date'] = request.form['end_date']
        session['gender'] = request.form['gender']
        session['companions'] = request.form['companions']
        session['age'] = request.form['age']
        session['preference'] = request.form['preference']
        session['budget'] = request.form['budget']
        session['departure_city'] = request.form['departure_city']

        start_date = session['start_date']
        end_date = session['end_date']
        departure_city = session['departure_city']

        # 날짜 변환
        start_date_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.datetime.strptime(end_date, "%Y-%m-%d")

        # 1년 전 날짜 계산
        start_date_last_year = start_date_obj - datetime.timedelta(days=365)
        end_date_last_year = end_date_obj - datetime.timedelta(days=365)

        # 타임스탬프로 변환
        start_timestamp = int(start_date_last_year.timestamp())
        end_timestamp = int(end_date_last_year.timestamp())

        # 여행지 추천을 위한 ChatGPT API 호출
        prompt = (
                    f"You are a travel abroad assistant. Recommend a specific city that fits the following conditions, and only return the city name (no other information): "
                    f"\n- Budget: {session['budget']} KRW for the entire trip."
                    f"\n- Traveler: {session['age']}-year-old {session['gender']} traveling with {session['companions']}."
                    f"\n- Travel dates: From {start_date} to {end_date}."
                    f"\n- Preferences: The traveler prefers {session['preference']} type of destinations."
                    f"\n- Departure city: {departure_city}."
                    f"\nProvide the best possible city destination for this trip, considering the Departure city, budget, flight time and preferences ."
                    f"Please print city in Korean and except the country name"
                )

        chatgpt_response = call_chatgpt(prompt)
        session['city_name'] = chatgpt_response['choices'][0]['message']['content'].strip()

        # 위도/경도 가져오기
        latitude, longitude = get_lat_long(session['city_name'])
        if latitude and longitude:
            try:
                # 날씨 데이터 가져오기
                weather_data = get_weather_data(latitude, longitude, start_timestamp, end_timestamp)

                # 식당 및 호텔 정보 가져오기
                api_key = os.getenv('GOOGLE_API_KEY')
                restaurants_data = get_restaurants(session['city_name'], api_key)
                hotels_data = get_hotels(session['city_name'], api_key)

                # 필요한 정보만 전달하기 위해 리스트로 구성
                restaurants_info = [{'name': restaurant['name'], 'address': restaurant.get('formatted_address', '주소 없음')} for restaurant in restaurants_data['results']]
                hotels_info = [{'name': hotel['name'], 'address': hotel.get('formatted_address', '주소 없음')} for hotel in hotels_data['results']]

                # 결과 템플릿 렌더링
                return render_template(
                    'results_international.html',
                    city_name=session['city_name'],
                    weather_data=weather_data,
                    restaurants=restaurants_info,
                    hotels=hotels_info,
                    show_booking=True  # 항공권 예약 여부를 묻는 변수 추가
                )

            except requests.exceptions.HTTPError as err:
                result = f"기상 데이터를 가져오는 도중 오류가 발생했습니다: {err}"
        else:
            result = "위치 정보를 찾을 수 없습니다."

        return f'<pre>{result}</pre>'

    return render_template('form_international.html')


# Flight booking route
@app.route('/booking_flight')
def booking_flight():
    # 세션에서 필요한 데이터 가져오기
    start_date = session.get('start_date')
    end_date = session.get('end_date')
    departure_city = session.get('departure_city')
    city_name = session.get('city_name')

    # Selenium WebDriver 시작
    driver = webdriver.Chrome()
    driver.get('https://flight.naver.com/')

    wait = WebDriverWait(driver, 10)  # WebDriverWait 설정

    # 날짜 형식 변환
    start_list = start_date.split("-")
    start_day = start_list[2]
    start_month = start_list[0] + "." + start_list[1] + "."

    end_list = end_date.split("-")
    end_day = end_list[2]
    end_month = end_list[0] + "." + end_list[1] + "."

    try:
        # 출발지 입력
        start_area_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__next"]/div/main/div[2]/div/div/div[2]/div[1]/button[1]')))
        driver.execute_script("arguments[0].click();", start_area_button)  # JavaScript로 클릭 강제 실행
        time.sleep(2)
        search_area = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'autocomplete_input__qbYlb')))
        search_area.send_keys(departure_city)
        time.sleep(2)
        finish_area = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'autocomplete_inner__xHAxv')))
        driver.execute_script("arguments[0].click();", finish_area)
        
        # 도착지 입력
        end_area_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__next"]/div/main/div[2]/div/div/div[2]/div[1]/button[2]')))
        driver.execute_script("arguments[0].click();", end_area_button)
        time.sleep(2)
        search_area = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'autocomplete_input__qbYlb')))
        search_area.send_keys(city_name)
        time.sleep(2)
        finish_area = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'autocomplete_inner__xHAxv')))
        driver.execute_script("arguments[0].click();", finish_area)
        
        # 날짜 선택
        day_area_start = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__next"]/div/main/div[2]/div/div/div[2]/div[2]/button[1]')))
        driver.execute_script("arguments[0].click();", day_area_start)
        time.sleep(8)
        select_day(driver, start_month, start_day)
        
        day_area_end = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="__next"]/div/main/div[2]/div/div/div[2]/div[2]/button[2]')))
        driver.execute_script("arguments[0].click();", day_area_end)
        time.sleep(8)
        select_day(driver, end_month, end_day)

        # 검색 버튼 클릭
        element = driver.find_element(By.CSS_SELECTOR, "button.searchBox_search__dgK4Z")
        driver.execute_script("arguments[0].click();", element)

    except TimeoutException:
        print("페이지 요소를 찾는 데 시간이 너무 오래 걸립니다.")
    except Exception as e:
        print(f"예상치 못한 에러가 발생했습니다: {str(e)}")

    input("Press Enter to close the browser")
    driver.quit()

    return "항공권 예약이 완료되었습니다."

# Selenium 날짜 선택 함수
def select_day(driver, input_month, input_day):
    all_day = driver.find_elements(By.CLASS_NAME,'sc-kpDqfm.ljuuWQ.month')
    month_day = []
    for i in all_day:
        month = i.find_elements(By.CLASS_NAME,'sc-dAlyuH.cKxEnD')
        for j in month:
            if j.text == input_month:
                month_day = i.find_elements(By.CSS_SELECTOR,'.day b')
    for i in month_day:
        if i.text == input_day:
            i.click()
            break

if __name__ == '__main__':
    app.run(debug=True)