self.addEventListener('push', function(event) {
  let data = {

  }
  if (event.data) {
      data = event.data.json();
  }  
  let options = {
    body: data.message,
    data: {
        url: data.url
    }
  };

  event.waitUntil(
      self.registration.showNotification('Hotdeal Alarm', options)
  );
});

self.addEventListener('notificationclick', function(event) {
  let data = event.notification.data;
  let url = data.url ? data.url : 'https://google.com/'
  event.notification.close();
  event.waitUntil(
      clients.openWindow(url) // 알림을 클릭했을 때 열 페이지 URL
  );
});
