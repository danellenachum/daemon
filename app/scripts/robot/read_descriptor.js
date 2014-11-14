// Generated by CoffeeScript 1.8.0
angular.module('daemon.read_descriptor.coffee', []).service('read_descriptor', [
  function() {
    var buffer, calibrationType, readChannelDescriptor, readString, typeChannel;
    buffer = require("buffer");
    readString = function(buf, startIndex) {
      var description, length;
      length = buf.readUInt8(startIndex);
      description = buf.slice(startIndex + 1, length + startIndex + 1);
      return [description.toString("utf8"), length + startIndex + 1];
    };
    readChannelDescriptor = function(buf, startIndex) {
      var channelDescriptor, descriptors, i, index, numChannels, type, typeData;
      descriptors = [];
      index = startIndex + 1;
      numChannels = buf.readUInt8(startIndex);
      i = 0;
      while (i < numChannels) {
        channelDescriptor = readString(buf, index + 1);
        type = buf.readUInt8(channelDescriptor[1]);
        typeData = typeChannel(buf, type, channelDescriptor[1] + 1);
        descriptors.push([channelDescriptor[0], typeData[0]]);
        index = typeData[1];
        i++;
      }
      return descriptors;
    };
    typeChannel = function(buf, typeBinary, startIndex) {
      var BIT_PER_SAMPLE_LENGTH, FLAGS_LENGTH, INTERNAL_CYCLE_TIME_TICK_LENGTH, INTERNAL_TIMER_TICK_FREQ_LENGTH, MODE, SAMPLE_RATE_LENGTH, SPEED, num, numTotal, typeString;
      FLAGS_LENGTH = 1;
      SAMPLE_RATE_LENGTH = 2;
      BIT_PER_SAMPLE_LENGTH = 1;
      INTERNAL_TIMER_TICK_FREQ_LENGTH = 4;
      INTERNAL_CYCLE_TIME_TICK_LENGTH = 4;
      MODE = 1;
      SPEED = 4;
      numTotal = startIndex;
      typeString = "";
      switch (typeBinary) {
        case 0x00:
          numTotal += FLAGS_LENGTH + SAMPLE_RATE_LENGTH;
          typeString = "Digital In/Out";
          break;
        case 0x01:
          num = numTotal + SAMPLE_RATE_LENGTH + BIT_PER_SAMPLE_LENGTH;
          numTotal = calibrationType(buf, num);
          typeString = "Analog Input";
          break;
        case 0x02:
          num = numTotal + SAMPLE_RATE_LENGTH + BIT_PER_SAMPLE_LENGTH;
          numTotal = calibrationType(buf, num);
          typeString = "Analog Output";
          break;
        case 0x03:
          num = numTotal + BIT_PER_SAMPLE_LENGTH + INTERNAL_TIMER_TICK_FREQ_LENGTH + INTERNAL_CYCLE_TIME_TICK_LENGTH;
          numTotal = calibrationType(buf, num);
          typeString = "Hobby Servo";
          break;
        case 0x40:
          typeString = "Generic I2C";
          break;
        case 0x41:
          typeString = "Generic SPI";
          break;
        case 0x42:
          typeString = "Generic UART";
          break;
        case 0x80:
          numTotal += MODE + SPEED;
          typeString = "Grizzly Bear v3";
          break;
        case 0x81:
          num = numTotal + SAMPLE_RATE_LENGTH + BIT_PER_SAMPLE_LENGTH;
          numTotal = calibrationType(buf, num);
          typeString = "Battery Buzzer";
          break;
        case 0x82:
          numTotal += FLAGS_LENGTH + SAMPLE_RATE_LENGTH;
          typeString = "Team Flag";
          break;
        case 0xfe:
          typeString = "Actuator Mode";
          break;
        case 0xff:
          typeString = "debugger";
      }
      return [typeString, numTotal];
    };
    calibrationType = function(buf, startIndex) {
      var COUNT_ENTRIES_LENGTH, FLOAT_LENGTH, countEntries, numTotal, type;
      type = buf.readUInt8(startIndex);
      numTotal = startIndex + 1;
      FLOAT_LENGTH = 4;
      COUNT_ENTRIES_LENGTH = 4;
      switch (type) {
        case 0x00:
          numTotal += 0;
          break;
        case 0x01:
          numTotal += 2 * FLOAT_LENGTH;
          break;
        case 0x02:
          numTotal += 3 * FLOAT_LENGTH;
          break;
        case 0x03:
          numTotal += 3 * FLOAT_LENGTH;
          break;
        case 0x04:
          countEntries = buf.readUInt32LE(numTotal);
          numTotal += COUNT_ENTRIES_LENGTH + countEntries * 2 * FLOAT_LENGTH;
      }
      return numTotal;
    };
    return readChannelDescriptor;
  }
]);
